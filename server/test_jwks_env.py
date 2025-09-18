#!/usr/bin/env python3
"""
Test script for JWKS endpoint in different environments
"""
import os
import sys

# Add server path
server_path = '/Users/iiii/Documents/(AiG) Artificial intelligent Generation /Разработка/tg sender/SLAVA/SLAVA App 2.0/server'
sys.path.insert(0, server_path)

def test_jwks_environment(env_name, expected_format):
    print(f"\n=== Testing {env_name} Environment ===")

    # Set environment
    os.environ['ENV'] = env_name

    # Clear module cache
    modules_to_clear = [k for k in sys.modules.keys() if k.startswith('app')]
    for module in modules_to_clear:
        del sys.modules[module]

    try:
        from app.api.routes.jwks import jwks
        result = jwks()

        key = result['keys'][0]
        print(f"kid: {key['kid']}")
        print(f"kty: {key['kty']}")
        print(f"alg: {key['alg']}")

        if 'pem' in key:
            print("✅ Format: PEM (for development)")
            print(f"PEM length: {len(key['pem'])} chars")
        elif 'n' in key and 'e' in key:
            print("✅ Format: JWK (for stage/production)")
            print(f"n parameter: {key['n'][:30]}...")
            print(f"e parameter: {key['e']}")
        else:
            print("❌ Unknown format")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing JWKS endpoint for different environments...")

    # Test dev environment
    test_jwks_environment("dev", "PEM")

    # Test stage environment
    test_jwks_environment("stage", "JWK")

    print("\n✅ JWKS environment testing completed!")
