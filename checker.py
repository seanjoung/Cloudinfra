#!/usr/bin/env python3
"""
CMP 인프라 점검 모듈
OS, Kubernetes 클러스터, K8s 서비스, CI/CD, DB 점검
"""

import yaml
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

from ssh_executor import get_executor, RemoteExecutor, ConnectionResult


class CheckStatus(Enum):
    OK = "정상"
    WARNING = "경고"
    CRITICAL = "위험"
    UNKNOWN = "확인불가"


@dataclass
class CheckResult:
    """점검 결과"""
    check_id: str
    name: str
    category: str
    subcategory: str  # 환경 (DEV/STG/PRD) 또는 서버명
    description: str
    status: CheckStatus
    value: str
    threshold: Optional[float]
    unit: str
    message: str
    target: str  # 점검 대상 (호스트명 또는 서비스명)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    severity: str = "medium"


class CMPInfraChecker:
    """CMP 인프라 점검 클래스"""
    
    def __init__(self, 
                 inventory_path: str = "config/inventory.yaml",
                 checks_path: str = "config/check_items.yaml",
                 demo_mode: bool = False):
        
        self.inventory_path = inventory_path
        self.checks_config = self._load_config(checks_path)
        self.executor = get_executor(demo_mode=demo_mode, inventory_path=inventory_path)
        self.demo_mode = demo_mode
        self.results: List[CheckResult] = []
        
    def _load_config(self, path: str) -> dict:
        """설정 파일 로드"""
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _evaluate_threshold(self, value: str, threshold: float, 
                           check_id: str) -> Tuple[CheckStatus, str]:
        """임계치 기반 상태 평가"""
        try:
            numeric_value = float(value.replace('%', '').strip())
            
            # 0이 정상인 항목들
            zero_is_ok = ['OS-005', 'K8S-008', 'K8S-009', 'SVC-004', 
                          'SVC-006', 'SVC-007', 'SVC-008', 'SVC-010']
            
            if check_id in zero_is_ok:
                if numeric_value == 0:
                    return CheckStatus.OK, "정상"
                elif numeric_value <= 3:
                    return CheckStatus.WARNING, f"주의 필요 ({numeric_value}개)"
                else:
                    return CheckStatus.CRITICAL, f"즉시 조치 필요 ({numeric_value}개)"
            else:
                if numeric_value < threshold * 0.8:
                    return CheckStatus.OK, "정상 범위"
                elif numeric_value < threshold:
                    return CheckStatus.WARNING, f"임계치 근접 ({threshold})"
                else:
                    return CheckStatus.CRITICAL, f"임계치 초과 ({threshold})"
                    
        except (ValueError, AttributeError):
            return CheckStatus.UNKNOWN, "값 파싱 실패"
    
    def _evaluate_expected(self, output: str, expected: str) -> Tuple[CheckStatus, str]:
        """기대값 기반 상태 평가"""
        if not output or output == 'N/A':
            return CheckStatus.UNKNOWN, "데이터 없음"
        
        lines = [l.strip() for l in output.strip().split('\n') if l.strip()]
        if not lines:
            return CheckStatus.UNKNOWN, "점검 대상 없음"
        
        total = len(lines)
        ok_count = sum(1 for line in lines if expected in line)
        
        if ok_count == total:
            return CheckStatus.OK, f"모두 정상 ({ok_count}/{total})"
        elif ok_count >= total * 0.7:
            return CheckStatus.WARNING, f"일부 이상 ({ok_count}/{total} 정상)"
        else:
            return CheckStatus.CRITICAL, f"다수 이상 ({total - ok_count}개 문제)"
    
    # ==========================================
    # OS 점검
    # ==========================================
    def check_os(self, servers: List[Dict], env_name: str = "") -> List[CheckResult]:
        """OS 점검 실행"""
        results = []
        os_checks = self.checks_config.get('os_checks', [])
        
        for server in servers:
            hostname = server.get('hostname', '')
            ip = server.get('ip', '')
            port = server.get('port', 22)
            server_name = server.get('name', hostname)
            category = server.get('category', 'OS')
            
            for check in os_checks:
                if self.demo_mode:
                    result = self._run_demo_os_check(check, server_name, category, env_name)
                else:
                    result = self._run_os_check(check, hostname, ip, port, 
                                                server_name, category, env_name)
                results.append(result)
        
        return results
    
    def _run_os_check(self, check: dict, hostname: str, ip: str, port: int,
                      server_name: str, category: str, env_name: str) -> CheckResult:
        """실제 OS 점검 실행"""
        check_id = check['id']
        
        conn_result = self.executor.execute_ssh(hostname, ip, check['command'], port)
        
        if not conn_result.success:
            return CheckResult(
                check_id=check_id,
                name=check['name'],
                category=category,
                subcategory=env_name,
                description=check['description'],
                status=CheckStatus.UNKNOWN,
                value="N/A",
                threshold=check.get('threshold'),
                unit=check.get('unit', ''),
                message=conn_result.error_message or "연결 실패",
                target=server_name,
                severity=check.get('severity', 'medium')
            )
        
        value = conn_result.stdout
        threshold = check.get('threshold')
        
        if threshold is not None:
            status, message = self._evaluate_threshold(value, threshold, check_id)
        else:
            status = CheckStatus.OK
            message = "정보 수집 완료"
        
        return CheckResult(
            check_id=check_id,
            name=check['name'],
            category=category,
            subcategory=env_name,
            description=check['description'],
            status=status,
            value=value,
            threshold=threshold,
            unit=check.get('unit', ''),
            message=message,
            target=server_name,
            severity=check.get('severity', 'medium')
        )
    
    def _run_demo_os_check(self, check: dict, server_name: str, 
                           category: str, env_name: str) -> CheckResult:
        """데모 모드 OS 점검"""
        demo_values = {
            'OS-001': ('45', CheckStatus.OK, '정상 범위'),
            'OS-002': ('62.5', CheckStatus.OK, '정상 범위'),
            'OS-003': ('23', CheckStatus.OK, '정상 범위'),
            'OS-004': ('up 15 days, 4 hours', CheckStatus.OK, '정상 가동 중'),
            'OS-005': ('0', CheckStatus.OK, '좀비 프로세스 없음'),
            'OS-006': ('1.25', CheckStatus.OK, '정상 범위'),
            'OS-007': ('12.3', CheckStatus.OK, '정상 범위'),
            'OS-008': ('3456', CheckStatus.OK, '정상 범위'),
            'OS-009': ('128', CheckStatus.OK, '정상 범위'),
            'OS-010': ('5.15.0-91-generic', CheckStatus.OK, '커널 정보 확인'),
        }
        
        check_id = check['id']
        value, status, message = demo_values.get(check_id, ('N/A', CheckStatus.UNKNOWN, '데모 데이터 없음'))
        
        return CheckResult(
            check_id=check_id,
            name=check['name'],
            category=category,
            subcategory=env_name,
            description=check['description'],
            status=status,
            value=value,
            threshold=check.get('threshold'),
            unit=check.get('unit', ''),
            message=message,
            target=server_name,
            severity=check.get('severity', 'medium')
        )
    
    # ==========================================
    # Kubernetes 클러스터 점검
    # ==========================================
    def check_k8s_cluster(self, cluster_key: str) -> List[CheckResult]:
        """Kubernetes 클러스터 점검"""
        results = []
        cluster = self.executor.get_cluster_info(cluster_key)
        
        if not cluster:
            return results
        
        env_name = cluster.get('env', cluster_key.upper())
        k8s_checks = self.checks_config.get('k8s_cluster_checks', [])
        
        # Master 노드 중 첫 번째에서 kubectl 실행
        masters = cluster.get('masters', [])
        if not masters:
            return results
        
        master = masters[0]
        hostname = master.get('hostname', '')
        ip = master.get('ip', '')
        port = master.get('ssh_port', 22)
        
        for check in k8s_checks:
            if self.demo_mode:
                result = self._run_demo_k8s_check(check, env_name)
            else:
                result = self._run_k8s_check(check, hostname, ip, port, env_name)
            results.append(result)
        
        return results
    
    def _run_k8s_check(self, check: dict, hostname: str, ip: str, 
                       port: int, env_name: str) -> CheckResult:
        """실제 K8s 클러스터 점검"""
        check_id = check['id']
        
        conn_result = self.executor.execute_ssh(hostname, ip, check['command'], port)
        
        if not conn_result.success:
            return CheckResult(
                check_id=check_id,
                name=check['name'],
                category="Kubernetes",
                subcategory=env_name,
                description=check['description'],
                status=CheckStatus.UNKNOWN,
                value="N/A",
                threshold=check.get('threshold'),
                unit=check.get('unit', ''),
                message=conn_result.error_message or "kubectl 실행 실패",
                target=f"{env_name} Cluster",
                severity=check.get('severity', 'medium')
            )
        
        value = conn_result.stdout
        expected = check.get('expected')
        threshold = check.get('threshold')
        
        if expected:
            status, message = self._evaluate_expected(value, expected)
        elif threshold is not None:
            status, message = self._evaluate_threshold(value, threshold, check_id)
        else:
            status = CheckStatus.OK
            message = "정보 수집 완료"
        
        return CheckResult(
            check_id=check_id,
            name=check['name'],
            category="Kubernetes",
            subcategory=env_name,
            description=check['description'],
            status=status,
            value=value[:200] if value else "N/A",
            threshold=threshold,
            unit=check.get('unit', ''),
            message=message,
            target=f"{env_name} Cluster",
            severity=check.get('severity', 'medium')
        )
    
    def _run_demo_k8s_check(self, check: dict, env_name: str) -> CheckResult:
        """데모 모드 K8s 클러스터 점검"""
        demo_values = {
            'K8S-001': ('master-01:Ready\nmaster-02:Ready\nmaster-03:Ready\nworker-01:Ready\nworker-02:Ready\nworker-03:Ready', 
                        CheckStatus.OK, '모두 정상 (6/6)'),
            'K8S-002': ('master-01:32%\nworker-01:45%\nworker-02:38%\nworker-03:52%', 
                        CheckStatus.OK, '모든 노드 정상'),
            'K8S-003': ('master-01:58%\nworker-01:62%\nworker-02:55%\nworker-03:71%', 
                        CheckStatus.OK, '모든 노드 정상'),
            'K8S-004': ('coredns-xxx:Running\netcd-master:Running\nkube-apiserver:Running\nkube-scheduler:Running', 
                        CheckStatus.OK, '모든 시스템 Pod 정상'),
            'K8S-005': ('etcd-master-01:Running\netcd-master-02:Running\netcd-master-03:Running', 
                        CheckStatus.OK, 'etcd 클러스터 정상'),
            'K8S-006': ('pv-data-01:Bound\npv-data-02:Bound', 
                        CheckStatus.OK, '모든 PV Bound'),
            'K8S-007': ('pvc-01:Bound\npvc-02:Bound', 
                        CheckStatus.OK, '모든 PVC Bound'),
            'K8S-008': ('5', CheckStatus.OK, 'Warning 이벤트 정상 범위'),
            'K8S-009': ('0', CheckStatus.OK, 'NotReady 노드 없음'),
            'K8S-010': ('v1.28.4', CheckStatus.OK, '버전 정보 확인'),
        }
        
        check_id = check['id']
        value, status, message = demo_values.get(check_id, ('N/A', CheckStatus.UNKNOWN, '데모 데이터 없음'))
        
        return CheckResult(
            check_id=check_id,
            name=check['name'],
            category="Kubernetes",
            subcategory=env_name,
            description=check['description'],
            status=status,
            value=value,
            threshold=check.get('threshold'),
            unit=check.get('unit', ''),
            message=message,
            target=f"{env_name} Cluster",
            severity=check.get('severity', 'medium')
        )
    
    # ==========================================
    # K8s 서비스/워크로드 점검
    # ==========================================
    def check_k8s_services(self, cluster_key: str) -> List[CheckResult]:
        """K8s 서비스/워크로드 점검"""
        results = []
        cluster = self.executor.get_cluster_info(cluster_key)
        
        if not cluster:
            return results
        
        env_name = cluster.get('env', cluster_key.upper())
        svc_checks = self.checks_config.get('k8s_service_checks', [])
        
        masters = cluster.get('masters', [])
        if not masters:
            return results
        
        master = masters[0]
        hostname = master.get('hostname', '')
        ip = master.get('ip', '')
        port = master.get('ssh_port', 22)
        
        for check in svc_checks:
            if self.demo_mode:
                result = self._run_demo_svc_check(check, env_name)
            else:
                result = self._run_svc_check(check, hostname, ip, port, env_name)
            results.append(result)
        
        return results
    
    def _run_svc_check(self, check: dict, hostname: str, ip: str, 
                       port: int, env_name: str) -> CheckResult:
        """실제 K8s 서비스 점검"""
        check_id = check['id']
        
        conn_result = self.executor.execute_ssh(hostname, ip, check['command'], port)
        
        if not conn_result.success:
            return CheckResult(
                check_id=check_id,
                name=check['name'],
                category="Services",
                subcategory=env_name,
                description=check['description'],
                status=CheckStatus.UNKNOWN,
                value="N/A",
                threshold=check.get('threshold'),
                unit=check.get('unit', ''),
                message=conn_result.error_message or "점검 실패",
                target=f"{env_name} Services",
                severity=check.get('severity', 'medium')
            )
        
        value = conn_result.stdout
        check_type = check.get('check_type', '')
        threshold = check.get('threshold')
        
        if check_type == 'replica_match':
            # 출력이 있으면 문제가 있는 것
            if value and value.strip():
                issues = value.strip().split('\n')
                status = CheckStatus.WARNING if len(issues) <= 3 else CheckStatus.CRITICAL
                message = f"불일치 리소스 {len(issues)}개"
            else:
                status = CheckStatus.OK
                value = "모두 정상"
                message = "모든 리소스 정상"
        elif threshold is not None:
            status, message = self._evaluate_threshold(value or '0', threshold, check_id)
        else:
            status = CheckStatus.OK
            message = "정보 수집 완료"
        
        return CheckResult(
            check_id=check_id,
            name=check['name'],
            category="Services",
            subcategory=env_name,
            description=check['description'],
            status=status,
            value=value[:200] if value else "0",
            threshold=threshold,
            unit=check.get('unit', ''),
            message=message,
            target=f"{env_name} Services",
            severity=check.get('severity', 'medium')
        )
    
    def _run_demo_svc_check(self, check: dict, env_name: str) -> CheckResult:
        """데모 모드 서비스 점검"""
        demo_values = {
            'SVC-001': ('', CheckStatus.OK, '모든 Deployment 정상'),
            'SVC-002': ('', CheckStatus.OK, '모든 StatefulSet 정상'),
            'SVC-003': ('', CheckStatus.OK, '모든 DaemonSet 정상'),
            'SVC-004': ('0', CheckStatus.OK, 'Endpoint 없는 Service 없음'),
            'SVC-005': ('5', CheckStatus.OK, '5개 Ingress 확인'),
            'SVC-006': ('', CheckStatus.OK, '과다 재시작 Pod 없음'),
            'SVC-007': ('0', CheckStatus.OK, 'Pending Pod 없음'),
            'SVC-008': ('0', CheckStatus.OK, 'Failed Pod 없음'),
            'SVC-009': ('3', CheckStatus.OK, '3개 CronJob 확인'),
            'SVC-010': ('0', CheckStatus.OK, 'Failed Job 없음'),
        }
        
        check_id = check['id']
        value, status, message = demo_values.get(check_id, ('N/A', CheckStatus.UNKNOWN, '데모 데이터 없음'))
        
        return CheckResult(
            check_id=check_id,
            name=check['name'],
            category="Services",
            subcategory=env_name,
            description=check['description'],
            status=status,
            value=value if value else "모두 정상",
            threshold=check.get('threshold'),
            unit=check.get('unit', ''),
            message=message,
            target=f"{env_name} Services",
            severity=check.get('severity', 'medium')
        )
    
    # ==========================================
    # CI/CD 서비스 점검
    # ==========================================
    def check_cicd_services(self) -> List[CheckResult]:
        """CI/CD 서비스 점검"""
        results = []
        cicd_servers = self.executor.get_cicd_servers()
        
        for key, server in cicd_servers.items():
            hostname = server.get('hostname', '')
            ip = server.get('ip', '')
            server_name = server.get('name', key)
            services = server.get('services', [])
            
            for service in services:
                svc_name = service.get('name', '')
                port = service.get('port', 80)
                
                if self.demo_mode:
                    status = CheckStatus.OK
                    message = "서비스 정상 응답"
                    value = "200 OK"
                else:
                    # HTTP 서비스 확인
                    url = f"http://{ip}:{port}/"
                    success, status_code = self.executor.check_http_status(url)
                    
                    if success:
                        status = CheckStatus.OK
                        message = "서비스 정상 응답"
                        value = f"{status_code} OK"
                    else:
                        # TCP 포트만 확인
                        if self.executor.check_tcp_port(ip, port):
                            status = CheckStatus.OK
                            message = "포트 응답 정상"
                            value = f"TCP {port} Open"
                        else:
                            status = CheckStatus.CRITICAL
                            message = "서비스 응답 없음"
                            value = "연결 실패"
                
                results.append(CheckResult(
                    check_id=f"CICD-{key.upper()[:3]}",
                    name=f"{svc_name} 서비스",
                    category="CI/CD",
                    subcategory="CI/CD 인프라",
                    description=f"{server_name} {svc_name} 서비스 상태",
                    status=status,
                    value=value,
                    threshold=None,
                    unit="",
                    message=message,
                    target=server_name,
                    severity="critical"
                ))
        
        return results
    
    # ==========================================
    # 데이터베이스 점검
    # ==========================================
    def check_databases(self, cluster_key: str) -> List[CheckResult]:
        """데이터베이스 점검"""
        results = []
        cluster = self.executor.get_cluster_info(cluster_key)
        
        if not cluster:
            return results
        
        env_name = cluster.get('env', cluster_key.upper())
        databases = cluster.get('databases', [])
        
        for db in databases:
            hostname = db.get('hostname', '')
            ip = db.get('ip', '')
            db_name = db.get('name', '')
            services = db.get('services', [])
            
            for service in services:
                svc_name = service.get('name', 'MySQL')
                port = service.get('port', 3306)
                
                if self.demo_mode:
                    status = CheckStatus.OK
                    message = "DB 연결 정상"
                    value = f"TCP {port} Open"
                else:
                    if self.executor.check_tcp_port(ip, port):
                        status = CheckStatus.OK
                        message = "DB 연결 정상"
                        value = f"TCP {port} Open"
                    else:
                        status = CheckStatus.CRITICAL
                        message = "DB 연결 실패"
                        value = "연결 불가"
                
                results.append(CheckResult(
                    check_id=f"DB-{env_name[:1]}{db_name[-1:]}",
                    name=f"{svc_name} 연결",
                    category="Database",
                    subcategory=env_name,
                    description=f"{db_name} {svc_name} 포트 연결 확인",
                    status=status,
                    value=value,
                    threshold=None,
                    unit="",
                    message=message,
                    target=f"{env_name} {db_name}",
                    severity="critical"
                ))
        
        return results
    
    # ==========================================
    # 전체 점검 실행
    # ==========================================
    def run_all_checks(self) -> List[CheckResult]:
        """모든 점검 실행"""
        self.results = []
        
        # 1. CI/CD 서비스 점검
        print("📋 CI/CD 서비스 점검 중...")
        self.results.extend(self.check_cicd_services())
        
        # 2. 개발 클러스터 점검
        print("📋 개발 클러스터(DEV) 점검 중...")
        dev_cluster = self.executor.get_cluster_info('dev_cluster')
        if dev_cluster:
            # OS 점검 (Masters + Workers)
            dev_servers = []
            for m in dev_cluster.get('masters', []):
                dev_servers.append({**m, 'category': 'DEV Master'})
            for w in dev_cluster.get('workers', []):
                dev_servers.append({**w, 'category': 'DEV Worker'})
            self.results.extend(self.check_os(dev_servers, 'DEV'))
            
            # K8s 클러스터 점검
            self.results.extend(self.check_k8s_cluster('dev_cluster'))
            
            # K8s 서비스 점검
            self.results.extend(self.check_k8s_services('dev_cluster'))
            
            # DB 점검
            self.results.extend(self.check_databases('dev_cluster'))
        
        # 3. 스테이징 클러스터 점검
        print("📋 스테이징 클러스터(STG) 점검 중...")
        stg_cluster = self.executor.get_cluster_info('stg_cluster')
        if stg_cluster:
            stg_servers = []
            for m in stg_cluster.get('masters', []):
                stg_servers.append({**m, 'category': 'STG Master'})
            for w in stg_cluster.get('workers', []):
                stg_servers.append({**w, 'category': 'STG Worker'})
            self.results.extend(self.check_os(stg_servers, 'STG'))
            self.results.extend(self.check_k8s_cluster('stg_cluster'))
            self.results.extend(self.check_k8s_services('stg_cluster'))
            self.results.extend(self.check_databases('stg_cluster'))
        
        # 4. 운영 클러스터 점검
        print("📋 운영 클러스터(PRD) 점검 중...")
        prd_cluster = self.executor.get_cluster_info('prd_cluster')
        if prd_cluster:
            prd_servers = []
            for m in prd_cluster.get('masters', []):
                prd_servers.append({**m, 'category': 'PRD Master'})
            for w in prd_cluster.get('workers', []):
                prd_servers.append({**w, 'category': 'PRD Worker'})
            self.results.extend(self.check_os(prd_servers, 'PRD'))
            self.results.extend(self.check_k8s_cluster('prd_cluster'))
            self.results.extend(self.check_k8s_services('prd_cluster'))
            self.results.extend(self.check_databases('prd_cluster'))
        
        return self.results
    
    def get_summary(self) -> Dict[str, Any]:
        """점검 결과 요약"""
        if not self.results:
            return {}
        
        summary = {
            'total': len(self.results),
            'ok': sum(1 for r in self.results if r.status == CheckStatus.OK),
            'warning': sum(1 for r in self.results if r.status == CheckStatus.WARNING),
            'critical': sum(1 for r in self.results if r.status == CheckStatus.CRITICAL),
            'unknown': sum(1 for r in self.results if r.status == CheckStatus.UNKNOWN),
            'by_environment': {},
            'by_category': {}
        }
        
        # 환경별 집계
        for r in self.results:
            env = r.subcategory
            if env not in summary['by_environment']:
                summary['by_environment'][env] = {'ok': 0, 'warning': 0, 'critical': 0, 'unknown': 0}
            
            if r.status == CheckStatus.OK:
                summary['by_environment'][env]['ok'] += 1
            elif r.status == CheckStatus.WARNING:
                summary['by_environment'][env]['warning'] += 1
            elif r.status == CheckStatus.CRITICAL:
                summary['by_environment'][env]['critical'] += 1
            else:
                summary['by_environment'][env]['unknown'] += 1
        
        # 카테고리별 집계
        for r in self.results:
            cat = r.category
            if cat not in summary['by_category']:
                summary['by_category'][cat] = {'ok': 0, 'warning': 0, 'critical': 0, 'unknown': 0}
            
            if r.status == CheckStatus.OK:
                summary['by_category'][cat]['ok'] += 1
            elif r.status == CheckStatus.WARNING:
                summary['by_category'][cat]['warning'] += 1
            elif r.status == CheckStatus.CRITICAL:
                summary['by_category'][cat]['critical'] += 1
            else:
                summary['by_category'][cat]['unknown'] += 1
        
        return summary
    
    def to_dict(self) -> List[Dict]:
        """결과를 딕셔너리 리스트로 변환"""
        return [
            {
                '점검ID': r.check_id,
                '점검항목': r.name,
                '카테고리': r.category,
                '환경': r.subcategory,
                '점검대상': r.target,
                '설명': r.description,
                '상태': r.status.value,
                '측정값': r.value,
                '임계치': f"{r.threshold}{r.unit}" if r.threshold else "-",
                '결과메시지': r.message,
                '중요도': r.severity,
                '점검시간': r.timestamp
            }
            for r in self.results
        ]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='데모 모드')
    args = parser.parse_args()
    
    checker = CMPInfraChecker(demo_mode=args.demo)
    results = checker.run_all_checks()
    summary = checker.get_summary()
    
    print("\n" + "=" * 60)
    print("📊 CMP 인프라 점검 결과 요약")
    print("=" * 60)
    print(f"총 점검 항목: {summary['total']}")
    print(f"  ✅ 정상: {summary['ok']}")
    print(f"  ⚠️  경고: {summary['warning']}")
    print(f"  ❌ 위험: {summary['critical']}")
    print(f"  ❓ 확인불가: {summary['unknown']}")
    print("=" * 60)
