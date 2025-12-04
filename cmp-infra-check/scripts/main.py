#!/usr/bin/env python3
"""
CMP 인프라 정기점검 - 메인 스크립트
OS, Kubernetes, K8s 서비스, CI/CD, DB 점검 및 보고서 생성

사용법:
    python main.py                      # 기본 실행
    python main.py --demo               # 데모 모드 (샘플 데이터)
    python main.py --type monthly       # 월간 보고서
    python main.py --env dev            # 특정 환경만 점검
"""

import argparse
import os
import sys
import yaml
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from checker import CMPInfraChecker
from report_generator import CMPReportGenerator, ReportConfig, generate_reports


def load_inventory_config(inventory_path: str) -> dict:
    """인벤토리 설정 로드"""
    with open(inventory_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def create_report_config(inventory: dict, report_type: str, output_dir: str = None) -> ReportConfig:
    """보고서 설정 생성"""
    report_conf = inventory.get('report', {})
    
    return ReportConfig(
        report_type=report_type or report_conf.get('type', 'weekly'),
        company_name=report_conf.get('company_name', 'CMP 인프라'),
        team_name=report_conf.get('team_name', '플랫폼팀'),
        output_dir=output_dir or report_conf.get('output_dir', './output')
    )


def format_issue_message(results: list) -> str:
    """이슈 메시지 포맷팅"""
    issues = [r for r in results if r.get('상태') in ['경고', '위험']]
    
    if not issues:
        return "모든 점검 항목이 정상입니다."
    
    lines = ["🚨 조치 필요 항목:"]
    for issue in issues:
        status = issue.get('상태', '')
        icon = "⚠️" if status == '경고' else "❌"
        lines.append(f"{icon} [{issue.get('점검ID')}] {issue.get('환경')} - {issue.get('점검항목')}")
        lines.append(f"   └─ {issue.get('결과메시지', '')}")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='CMP 인프라 정기점검 보고서 생성')
    
    parser.add_argument('--inventory', '-i',
        default=os.path.join(os.path.dirname(SCRIPT_DIR), 'config', 'inventory.yaml'),
        help='인벤토리 설정 파일 경로')
    parser.add_argument('--checks', '-c',
        default=os.path.join(os.path.dirname(SCRIPT_DIR), 'config', 'check_items.yaml'),
        help='점검 항목 설정 파일 경로')
    parser.add_argument('--type', '-t', choices=['weekly', 'monthly'], 
        default='weekly', help='보고서 유형')
    parser.add_argument('--output-dir', '-o', help='보고서 출력 디렉토리')
    parser.add_argument('--env', '-e', choices=['dev', 'stg', 'prd', 'all'], 
        default='all', help='점검할 환경 (기본: all)')
    parser.add_argument('--demo', action='store_true', help='데모 모드 (샘플 데이터 사용)')
    parser.add_argument('--json', action='store_true', help='JSON 형식 출력')
    parser.add_argument('--quiet', '-q', action='store_true', help='최소 출력')
    
    args = parser.parse_args()
    
    # 설정 파일 확인
    if not os.path.exists(args.inventory):
        print(f"❌ 인벤토리 파일을 찾을 수 없습니다: {args.inventory}")
        sys.exit(1)
    
    if not os.path.exists(args.checks):
        print(f"❌ 점검 항목 파일을 찾을 수 없습니다: {args.checks}")
        sys.exit(1)
    
    # 설정 로드
    inventory = load_inventory_config(args.inventory)
    report_config = create_report_config(inventory, args.type, args.output_dir)
    
    if not args.quiet:
        print("=" * 70)
        print("🔍 CMP 인프라 정기점검 시작")
        if args.demo:
            print("   ⚠️  데모 모드 - 샘플 데이터 사용")
        print(f"   보고서 유형: {report_config.report_type}")
        print(f"   회사: {report_config.company_name}")
        print(f"   담당팀: {report_config.team_name}")
        print(f"   점검 환경: {args.env.upper()}")
        print("=" * 70)
    
    # 점검 실행
    checker = CMPInfraChecker(
        inventory_path=args.inventory,
        checks_path=args.checks,
        demo_mode=args.demo
    )
    
    results = checker.run_all_checks()
    results_dict = checker.to_dict()
    summary = checker.get_summary()
    
    # JSON 출력
    if args.json:
        import json
        output = {
            'summary': summary,
            'results': results_dict,
            'timestamp': datetime.now().isoformat(),
            'demo_mode': args.demo
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    
    # 요약 출력
    if not args.quiet:
        print("\n" + "=" * 70)
        print("📊 점검 결과 요약")
        print("=" * 70)
        print(f"  총 점검항목: {summary['total']}")
        print(f"  ✅ 정상: {summary['ok']}")
        print(f"  ⚠️  경고: {summary['warning']}")
        print(f"  ❌ 위험: {summary['critical']}")
        print(f"  ❓ 확인불가: {summary['unknown']}")
        print("=" * 70)
        
        print("\n📂 환경별 결과:")
        for env, env_summary in summary.get('by_environment', {}).items():
            print(f"  {env}: ✅{env_summary['ok']} ⚠️{env_summary['warning']} ❌{env_summary['critical']} ❓{env_summary['unknown']}")
        
        print("\n📂 카테고리별 결과:")
        for cat, cat_summary in summary.get('by_category', {}).items():
            print(f"  {cat}: ✅{cat_summary['ok']} ⚠️{cat_summary['warning']} ❌{cat_summary['critical']} ❓{cat_summary['unknown']}")
    
    # 보고서 생성
    if not args.quiet:
        print("\n📝 보고서 생성 중...")
    
    generated_files = generate_reports(results_dict, summary, report_config)
    
    if not args.quiet:
        print("✅ 보고서 생성 완료:")
        for fmt, path in generated_files.items():
            print(f"   - {fmt.upper()}: {path}")
    
    # 조치 필요 항목 출력
    issues = [r for r in results_dict if r.get('상태') in ['경고', '위험']]
    if issues and not args.quiet:
        print("\n" + "=" * 70)
        print("🚨 조치 필요 항목")
        print("=" * 70)
        for issue in issues:
            status = issue.get('상태', '')
            icon = "⚠️" if status == '경고' else "❌"
            print(f"{icon} [{issue.get('점검ID')}] {issue.get('점검항목')}")
            print(f"   환경: {issue.get('환경', '')}")
            print(f"   대상: {issue.get('점검대상', '')}")
            print(f"   상태: {status}")
            print(f"   메시지: {issue.get('결과메시지', '')}")
            print()
    
    if not args.quiet:
        print("=" * 70)
        print("✅ 점검 완료")
        print("=" * 70)
    
    # 종료 코드
    if summary['critical'] > 0:
        sys.exit(2)
    elif summary['warning'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
