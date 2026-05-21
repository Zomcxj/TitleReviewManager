"""Test Phase 3 user management API."""
import subprocess, time, sys, os, json, requests as req

BASE = "http://localhost:8001"
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"],
    cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(4)

passed = 0
failed = 0

def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS: {name}")
    else:
        failed += 1; print(f"  FAIL: {name} {detail}")

try:
    s = req.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
    ok("admin login", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    assert r.status_code == 200, f"login failed: {r.text}"

    # List users
    r = s.get(f"{BASE}/api/users/")
    ok("list users", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    users = r.json()
    ok("has users", len(users) >= 5)
    ok("user has created_at", "created_at" in users[0])

    # Create user
    r = s.post(f"{BASE}/api/users/", json={"username": "testuser", "password": "test123", "role": "salesman", "real_name": "测试用户"})
    ok("create user", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    assert r.status_code == 200, f"create failed: {r.text}"
    new_id = r.json()["id"]

    # Duplicate username
    r = s.post(f"{BASE}/api/users/", json={"username": "testuser", "password": "test123", "role": "salesman"})
    ok("duplicate username rejected", r.status_code == 400)

    # Non-admin cannot create
    s2 = req.Session()
    r2 = s2.post(f"{BASE}/api/auth/login", json={"username": "salesman1", "password": "sales123"})
    assert r2.status_code == 200, f"salesman login failed: {r2.text}"
    r = s2.post(f"{BASE}/api/users/", json={"username": "hacker", "password": "hack123", "role": "admin"})
    ok("non-admin create rejected", r.status_code == 403)

    # Update user
    r = s.put(f"{BASE}/api/users/{new_id}", json={"real_name": "更新测试"})
    ok("update user", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    assert r.status_code == 200
    ok("name updated", r.json()["real_name"] == "更新测试")

    # Change own password
    s3 = req.Session()
    s3.post(f"{BASE}/api/auth/login", json={"username": "testuser", "password": "test123"})
    r = s3.post(f"{BASE}/api/users/change-password", json={"old_password": "test123", "new_password": "newpass123"})
    ok("change password", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # Login with new password
    r = s3.post(f"{BASE}/api/auth/login", json={"username": "testuser", "password": "newpass123"})
    ok("login with new password", r.status_code == 200)

    # Wrong old password
    r = s3.post(f"{BASE}/api/users/change-password", json={"old_password": "wrong", "new_password": "test123"})
    ok("wrong old password rejected", r.status_code == 400)

    # Delete user
    r = s.delete(f"{BASE}/api/users/{new_id}")
    ok("delete user", r.status_code == 200)
    r = s.get(f"{BASE}/api/users/{new_id}")
    ok("deleted user not found", r.status_code == 404)

    # Cannot delete self
    r = s.delete(f"{BASE}/api/users/1")
    ok("cannot delete self", r.status_code == 400)

finally:
    proc.terminate()
    proc.wait()

print(f"\nResults: {passed} passed, {failed} failed out of {passed+failed} tests")
sys.exit(1 if failed else 0)
