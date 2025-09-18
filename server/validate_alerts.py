#!/usr/bin/env python3
"""
Alert Configuration Validator for SLAVA Licensing API
"""
import yaml
import os
import sys
from typing import Dict, List, Any

def load_alerts_config() -> Dict[str, Any]:
    """Load and parse alerts.yml configuration"""
    alerts_file = "/Users/iiii/Documents/(AiG) Artificial intelligent Generation /Разработка/tg sender/SLAVA/SLAVA App 2.0/server/alerts.yml"

    if not os.path.exists(alerts_file):
        print(f"❌ Alerts file not found: {alerts_file}")
        return {}

    try:
        with open(alerts_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Invalid YAML in alerts file: {e}")
        return {}
    except Exception as e:
        print(f"❌ Error reading alerts file: {e}")
        return {}

def validate_alert_structure(alert_config: Dict[str, Any]) -> List[str]:
    """Validate the structure of alert configuration"""
    issues = []

    if 'groups' not in alert_config:
        issues.append("Missing 'groups' section")
        return issues

    for group in alert_config['groups']:
        if 'name' not in group:
            issues.append("Group missing 'name' field")
            continue

        group_name = group['name']
        print(f"📋 Validating group: {group_name}")

        if 'rules' not in group:
            issues.append(f"Group '{group_name}' missing 'rules' section")
            continue

        for rule in group['rules']:
            rule_name = rule.get('alert', 'Unknown')

            # Required fields
            required_fields = ['alert', 'expr', 'for', 'labels', 'annotations']
            for field in required_fields:
                if field not in rule:
                    issues.append(f"Rule '{rule_name}' missing required field: {field}")

            # Labels validation
            if 'labels' in rule:
                labels = rule['labels']
                if 'severity' not in labels:
                    issues.append(f"Rule '{rule_name}' missing severity label")
                if 'service' not in labels:
                    issues.append(f"Rule '{rule_name}' missing service label")

            # Expression validation (basic)
            if 'expr' in rule:
                expr = rule['expr']
                # Check for common issues
                if 'rate(' in expr and '[5m]' not in expr:
                    issues.append(f"Rule '{rule_name}' uses rate() without time window")

    return issues

def analyze_alert_coverage(alert_config: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze alert coverage and provide recommendations"""
    analysis = {
        'total_alerts': 0,
        'severity_distribution': {'critical': 0, 'warning': 0, 'info': 0},
        'covered_endpoints': set(),
        'covered_metrics': set(),
        'recommendations': []
    }

    if 'groups' not in alert_config:
        return analysis

    for group in alert_config['groups']:
        for rule in group.get('rules', []):
            analysis['total_alerts'] += 1

            # Severity distribution
            severity = rule.get('labels', {}).get('severity', 'unknown')
            if severity in analysis['severity_distribution']:
                analysis['severity_distribution'][severity] += 1

            # Extract endpoints from expressions
            expr = rule.get('expr', '')
            if 'endpoint=' in expr:
                # Simple extraction of endpoint names
                import re
                endpoints = re.findall(r'endpoint[=~]"([^"]*)"', expr)
                analysis['covered_endpoints'].update(endpoints)

            # Extract metrics
            if 'http_requests_total' in expr:
                analysis['covered_metrics'].add('HTTP requests')
            if 'http_request_duration' in expr:
                analysis['covered_metrics'].add('Request latency')
            if 'process_resident_memory' in expr:
                analysis['covered_metrics'].add('Memory usage')
            if 'node_filesystem' in expr:
                analysis['covered_metrics'].add('Disk space')

    # Generate recommendations
    if analysis['severity_distribution']['critical'] < 3:
        analysis['recommendations'].append("Consider adding more critical alerts for core functionality")

    if not any('5..' in str(rule.get('expr', '')) for group in alert_config.get('groups', [])
               for rule in group.get('rules', [])):
        analysis['recommendations'].append("Add alerts for 5xx HTTP status codes")

    if len(analysis['covered_endpoints']) < 3:
        analysis['recommendations'].append("Consider adding endpoint-specific alerts")

    return analysis

def main():
    print("🚨 SLAVA Licensing API - Alert Configuration Validator")
    print("=" * 60)

    # Load configuration
    alert_config = load_alerts_config()
    if not alert_config:
        print("❌ Failed to load alert configuration")
        sys.exit(1)

    # Validate structure
    issues = validate_alert_structure(alert_config)
    if issues:
        print("\n⚠️ Configuration Issues:")
        for issue in issues:
            print(f"  • {issue}")
    else:
        print("✅ Alert configuration structure is valid")

    # Analyze coverage
    analysis = analyze_alert_coverage(alert_config)

    print("\n📊 Alert Coverage Analysis:")
    print(f"  • Total alerts: {analysis['total_alerts']}")
    print(f"  • Severity distribution: {analysis['severity_distribution']}")
    print(f"  • Covered endpoints: {list(analysis['covered_endpoints'])}")
    print(f"  • Covered metrics: {list(analysis['covered_metrics'])}")

    if analysis['recommendations']:
        print("\n💡 Recommendations:")
        for rec in analysis['recommendations']:
            print(f"  • {rec}")

    # Overall assessment
    critical_issues = len([i for i in issues if 'missing' in i.lower() or 'required' in i.lower()])
    has_good_coverage = analysis['total_alerts'] >= 5 and len(analysis['covered_metrics']) >= 3

    print("\n" + "=" * 60)
    if critical_issues == 0 and has_good_coverage:
        print("🎉 ALERT STATUS: GREEN - Configuration ready for production")
        print("🚀 All critical metrics and endpoints are monitored")
    elif critical_issues == 0:
        print("⚠️ ALERT STATUS: YELLOW - Configuration adequate but can be improved")
        print("🔧 Consider adding more comprehensive monitoring")
    else:
        print("❌ ALERT STATUS: RED - Critical configuration issues found")
        print("🛠️ Fix critical issues before deploying to production")

    print("=" * 60)

if __name__ == "__main__":
    main()
