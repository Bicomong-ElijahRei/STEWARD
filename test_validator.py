import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database import DatabaseManager, init_db, get_db
from core.validator import (
    health_check, intelligence_probe, tool_calling_check,
    validate_provider, ValidationResult,
)

def test_environment():
    print("\\n" + "=" * 60)
    print("  PHASE 2 : Validation & Benchmarking")
    print("=" * 60)
    ok = True
    try:
        import cryptography
        print(f"[OK] cryptography {cryptography.__version__}")
    except ImportError:
        print("[FAIL] cryptography not installed")
        ok = False
    try:
        import requests
        print(f"[OK] requests {requests.__version__}")
    except ImportError:
        print("[FAIL] requests not installed")
        ok = False
    try:
        from cryptography.fernet import Fernet
        print(f"[OK] Fernet import OK")
    except ImportError as e:
        print(f"[FAIL] Fernet import error: {e}")
        ok = False
    return ok

def test_key_generation():
    print("\\n[1] Fernet key generation test")
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    f = Fernet(key)
    encrypted = f.encrypt(b"test-api-key")
    decrypted = f.decrypt(encrypted).decode("utf-8")
    print(f"    Encrypt/decrypt round-trip: {decrypted}")
    assert decrypted == "test-api-key"
    print("    OK")

def test_health_check_fake_key():
    print("\n[2] Health check with fake key (expected: invalid_key or connection_error if offline)")
    result = health_check(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="fake-key-12345",
        timeout=5,
    )
    print(f"    Status: {result.status}")
    print(f"    Error: {result.error}")
    assert result.status in ("invalid_key", "connection_error", "error")
    print("    OK (detected invalid key or offline state correctly)")

def test_health_check_local_ollama():
    print("\\n[3] Health check against local Ollama (if running)")
    ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_key = os.environ.get("OLLAMA_API_KEY", "")
    result = health_check(ollama_base, ollama_key or "noauth", timeout=5)
    if result.status == "healthy":
        print(f"    [OK] Connected to local Ollama at {ollama_base}")
        print(f"    Speed: {result.speed_ms} ms")
    elif result.status == "connection_error":
        print(f"    [SKIP] Local Ollama not running (connection_error)")
        print(f"    If Ollama is running, set OLLAMA_BASE_URL env var")
    else:
        print(f"    [INFO] Unexpected status: {result.status}")
    print("    OK (no crash)")

def test_full_pipeline():
    print("\\n[4] Full pipeline test (GEMINI_API_KEY required)")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("    [SKIP] GEMINI_API_KEY not set in environment")
        print("    Set it and rerun: export GEMINI_API_KEY=your_key")
        return
    base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    result = validate_provider(name="Gemini", base_url=base_url, api_key=api_key)
    print(f"    Provider: {result.provider}")
    print(f"    Speed: {result.speed_ms} ms")
    print(f"    Intelligence Tier: {result.intel_tier}")
    print(f"    Tool-calling: {result.supports_tools}")
    print(f"    Status: {result.status}")
    print(f"    Error: {result.error}")
    assert result.status == "healthy", f"Provider failed validation: {result}"
    assert result.intel_tier is not None
    print("    OK (validation passed)")

def test_db_integration():
    print("\\n[5] Database integration test")
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="steward_test_")
    db_path = os.path.join(tmpdir, "test.db")
    key_path = os.path.join(tmpdir, "secret.key")
    db = init_db(db_path=db_path, key_path=key_path)
    pid = db.add_provider(
        name="TestGemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model_name="gemini-2.0-flash",
        api_key="test-key-12345",
        is_local=False,
        is_active=True,
        speed_score_ms=850,
        intelligence_tier="Tier 1: Genius",
        supports_tools=True,
    )
    print(f"    [OK] Added provider TestGemini, id={pid}")
    assert pid is not None, "Provider id should not be None"
    db.update_provider_fields(
        name="TestGemini",
        speed_score_ms=620,
        intelligence_tier="Tier 1: Genius",
        supports_tools=True,
        failure_count=0,
    )
    provider = db.get_provider("TestGemini")
    print(f"    Speed score:   {provider['speed_score_ms']}")
    print(f"    Intelligence:  {provider['intelligence_tier']}")
    print(f"    Supports tools: {provider['supports_tools']}")
    print(f"    API key present (encrypted): {provider.get('api_key') is not None}")
    assert provider["speed_score_ms"] == 620
    assert provider["intelligence_tier"] == "Tier 1: Genius"
    assert provider["supports_tools"] is True
    assert provider["failure_count"] == 0
    db.close()
    print("    [OK] Database integration verified")

def main():
    parser = argparse.ArgumentParser(description="Phase 2 Validation Test")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
        help="Provider base URL",
    )
    parser.add_argument(
        "--api-key", help="Provider API key (defaults to GEMINI_API_KEY env var)",
    )
    args = parser.parse_args()
    if not args.api_key:
        args.api_key = os.environ.get("GEMINI_API_KEY", "")

    tests_passed = 0
    tests_failed = 0

    if test_environment():
        tests_passed += 1
    else:
        tests_failed += 1

    try:
        test_key_generation()
        tests_passed += 1
    except Exception as e:
        print(f"    FAILED: {e}")
        tests_failed += 1

    try:
        test_health_check_fake_key()
        tests_passed += 1
    except Exception as e:
        print(f"    FAILED: {e}")
        tests_failed += 1

    try:
        test_health_check_local_ollama()
        tests_passed += 1
    except Exception as e:
        print(f"    FAILED: {e}")
        tests_failed += 1

    if args.api_key:
        try:
            test_full_pipeline()
            tests_passed += 1
        except Exception as e:
            print(f"    FAILED: {e}")
            tests_failed += 1
    else:
        print("\\n[4] Full pipeline test skipped (no API key)")

    try:
        test_db_integration()
        tests_passed += 1
    except Exception as e:
        print(f"    FAILED: {e}")
        tests_failed += 1

    print("\\n" + "=" * 60)
    print(f"  Results: {tests_passed} passed, {tests_failed} failed")
    print("=" * 60)
    return tests_failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
