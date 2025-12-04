#!/bin/bash
#
# CMP 인프라 정기점검 스크립트
# OS, Kubernetes, K8s 서비스, CI/CD, DB 점검 및 보고서 생성
#
# 사용법:
#   ./cmp-infra-check.sh                  # 기본 실행 (주간)
#   ./cmp-infra-check.sh --demo           # 데모 모드
#   ./cmp-infra-check.sh --type monthly   # 월간 보고서
#   ./cmp-infra-check.sh --help           # 도움말
#
# 환경변수:
#   SSH_USER                - SSH 사용자 (기본: admin)
#   SSH_PRIVATE_KEY_PATH    - SSH 키 파일 경로
#   CMP_INVENTORY_PATH      - 인벤토리 파일 경로
#   SLACK_WEBHOOK_URL       - Slack 웹훅 URL
#

set -e

# 스크립트 경로
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/scripts/main.py"
INVENTORY_FILE="${SCRIPT_DIR}/config/inventory.yaml"
CHECKS_FILE="${SCRIPT_DIR}/config/check_items.yaml"
OUTPUT_DIR="${SCRIPT_DIR}/output"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 의존성 확인
check_dependencies() {
    log_info "의존성 확인 중..."
    
    # Python 확인
    if ! command -v python3 &> /dev/null; then
        log_error "Python3이 설치되어 있지 않습니다."
        exit 1
    fi
    
    # pip 패키지 확인 및 설치
    local packages=("pyyaml" "python-docx")
    for pkg in "${packages[@]}"; do
        if ! python3 -c "import ${pkg//-/_}" 2>/dev/null; then
            log_warning "${pkg} 패키지가 없습니다. 설치 중..."
            pip3 install ${pkg} --quiet --break-system-packages 2>/dev/null || \
            pip3 install ${pkg} --quiet 2>/dev/null || \
            log_warning "${pkg} 설치 실패. 일부 기능이 제한될 수 있습니다."
        fi
    done
    
    log_success "의존성 확인 완료"
}

# 설정 파일 확인
check_config_files() {
    log_info "설정 파일 확인 중..."
    
    if [ ! -f "${INVENTORY_FILE}" ]; then
        log_error "인벤토리 파일을 찾을 수 없습니다: ${INVENTORY_FILE}"
        log_info "config/inventory.yaml 파일을 생성하고 IP/Port 정보를 입력하세요."
        exit 1
    fi
    
    if [ ! -f "${CHECKS_FILE}" ]; then
        log_error "점검 항목 파일을 찾을 수 없습니다: ${CHECKS_FILE}"
        exit 1
    fi
    
    log_success "설정 파일 확인 완료"
}

# 출력 디렉토리 생성
setup_output_dir() {
    mkdir -p "${OUTPUT_DIR}"
}

# SSH 키 확인
check_ssh_key() {
    local ssh_key="${SSH_PRIVATE_KEY_PATH:-~/.ssh/id_rsa}"
    ssh_key=$(eval echo "${ssh_key}")
    
    if [ ! -f "${ssh_key}" ]; then
        log_warning "SSH 키 파일을 찾을 수 없습니다: ${ssh_key}"
        log_info "데모 모드로 실행하거나 SSH 키를 설정하세요."
    fi
}

# 도움말
show_help() {
    cat << EOF
CMP 인프라 정기점검 보고서 생성기

사용법:
    $0 [옵션]

옵션:
    --type, -t <weekly|monthly>    보고서 유형 (기본: weekly)
    --demo                         데모 모드 (샘플 데이터 사용)
    --env, -e <dev|stg|prd|all>    점검할 환경 (기본: all)
    --output-dir, -o <경로>        보고서 출력 디렉토리
    --json                         JSON 형식 출력
    --quiet, -q                    최소 출력
    --help, -h                     도움말 표시

환경변수:
    SSH_USER                       SSH 사용자 (기본: admin)
    SSH_PRIVATE_KEY_PATH           SSH 개인키 경로 (기본: ~/.ssh/id_rsa)
    CMP_INVENTORY_PATH             인벤토리 파일 경로
    SLACK_WEBHOOK_URL              Slack 웹훅 URL

예시:
    $0                             # 기본 실행
    $0 --demo                      # 데모 모드
    $0 --type monthly --env prd    # 월간 보고서, 운영환경만

보안 참고사항:
    - IP/Port 정보는 config/inventory.yaml에 별도 관리
    - inventory.yaml은 .gitignore에 추가 권장
    - SSH 키 파일 권한: chmod 600 ~/.ssh/id_rsa
    - 환경변수로 민감정보 관리 가능

Cron 예시:
    # 주간 점검 (매주 월요일 9시)
    0 9 * * 1 /path/to/cmp-infra-check.sh >> /var/log/cmp-check.log 2>&1
    
    # 월간 점검 (매월 1일 9시)
    0 9 1 * * /path/to/cmp-infra-check.sh --type monthly >> /var/log/cmp-check.log 2>&1

EOF
}

# 메인 실행
main() {
    echo ""
    echo "================================================================"
    echo "  🔍 CMP 인프라 정기점검 시스템"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "================================================================"
    echo ""
    
    check_dependencies
    check_config_files
    setup_output_dir
    check_ssh_key
    
    # Python 스크립트 실행
    python3 "${PYTHON_SCRIPT}" \
        --inventory "${INVENTORY_FILE}" \
        --checks "${CHECKS_FILE}" \
        --output-dir "${OUTPUT_DIR}" \
        "$@"
    
    local exit_code=$?
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        log_success "점검 완료: 모든 항목 정상"
    elif [ $exit_code -eq 1 ]; then
        log_warning "점검 완료: 경고 항목 발견"
    else
        log_error "점검 완료: 위험 항목 발견"
    fi
    
    exit $exit_code
}

# 인자 처리
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
    exit 0
fi

main "$@"
