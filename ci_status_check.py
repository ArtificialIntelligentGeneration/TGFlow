#!/usr/bin/env python3
"""
CI Status Check Script - имитирует проверку статуса CI pipeline
"""
import os
import sys
import subprocess
import time

def run_command(cmd, cwd=None):
    """Run command and return success status"""
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd,
                              capture_output=True, text=True, timeout=300)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def check_ci_components():
    """Check all CI components"""
    print("🚀 SLAVA Licensing API - CI Pipeline Status Check")
    print("=" * 60)

    server_dir = "/Users/iiii/Documents/(AiG) Artificial intelligent Generation /Разработка/tg sender/SLAVA/SLAVA App 2.0/server"
    base_dir = "/Users/iiii/Documents/(AiG) Artificial intelligent Generation /Разработка/tg sender/SLAVA/SLAVA App 2.0"

    results = []

    # 1. Check if CI workflow exists
    workflow_path = os.path.join(base_dir, ".github", "workflows", "ci.yml")
    if os.path.exists(workflow_path):
        results.append(("✅ CI Workflow", "Present", "ci.yml exists"))
    else:
        results.append(("❌ CI Workflow", "Missing", "ci.yml not found"))

    # 2. Check Python environment
    success, _, _ = run_command("python3 --version")
    if success:
        results.append(("✅ Python", "Available", "Python 3.x ready"))
    else:
        results.append(("❌ Python", "Missing", "Python not found"))

    # 3. Check dependencies installation
    success, _, _ = run_command("cd server && pip install -r requirements.txt --dry-run", cwd=base_dir)
    if success:
        results.append(("✅ Dependencies", "Installable", "requirements.txt valid"))
    else:
        results.append(("⚠️ Dependencies", "Check needed", "May have issues"))

    # 4. Check linting (ruff)
    success, _, _ = run_command("cd server && python -m ruff check . --select F", cwd=base_dir)
    if success:
        results.append(("✅ Linting", "Passed", "No critical issues"))
    else:
        results.append(("⚠️ Linting", "Issues found", "May need fixes"))

    # 5. Check OpenAPI spec
    openapi_path = os.path.join(server_dir, "openapi", "licensing.yml")
    if os.path.exists(openapi_path):
        results.append(("✅ OpenAPI Spec", "Present", "licensing.yml exists"))
    else:
        results.append(("❌ OpenAPI Spec", "Missing", "licensing.yml not found"))

    # 6. Check Dockerfile
    dockerfile_path = os.path.join(server_dir, "Dockerfile")
    if os.path.exists(dockerfile_path):
        results.append(("✅ Dockerfile", "Present", "Docker build ready"))
    else:
        results.append(("❌ Dockerfile", "Missing", "Dockerfile not found"))

    # 7. Test basic imports
    success, _, _ = run_command("cd server && python3 -c 'from app.main import app; print(app.title)'", cwd=base_dir)
    if success:
        results.append(("✅ App Import", "Working", "FastAPI app loads"))
    else:
        results.append(("❌ App Import", "Failed", "Import issues"))

    return results

def main():
    results = check_ci_components()

    print("\n📊 CI Components Status:")
    print("-" * 40)

    for component, status, details in results:
        print("25")

    print("\n" + "=" * 60)

    # Overall status
    failures = sum(1 for _, status, _ in results if "❌" in status or "Missing" in status)
    warnings = sum(1 for _, status, _ in results if "⚠️" in status or "Check needed" in status)

    if failures == 0 and warnings == 0:
        print("🎉 CI STATUS: GREEN - All components ready for deployment")
        print("🚀 Pipeline should pass successfully")
    elif failures == 0:
        print("⚠️ CI STATUS: YELLOW - Minor issues, should still pass")
        print("🔧 Recommend fixing warnings before production")
    else:
        print("❌ CI STATUS: RED - Critical issues found")
        print("🛠️ Fix critical issues before proceeding")

    print("=" * 60)

if __name__ == "__main__":
    main()
