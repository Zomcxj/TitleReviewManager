"""Test storage-backed materials API (upload/list/download/delete)."""
import subprocess, time, sys, os, json, requests as req

BASE = "http://localhost:8000"
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))

# 1. Start server
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
    cwd=BACKEND,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(3)

passed = 0
failed = 0

def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")

try:
    # 2. Login
    r = req.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"}, allow_redirects=False)
    ok("login returns 200", r.status_code == 200, f"got {r.status_code} body: {r.text[:200]}")
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.cookies.get("access_token") or r.json().get("access_token")
    cookies = {"access_token": token} if token else None

    # 3. Get customers
    r = req.get(f"{BASE}/api/customers", cookies=cookies)
    ok("list customers", r.status_code == 200)
    assert r.status_code == 200, f"list customers failed: {r.text[:200]}"
    customers = r.json()
    print(f"  customers type={type(customers).__name__}, first few keys={list(customers.keys())[:5] if isinstance(customers, dict) else 'list'}")
    if isinstance(customers, list):
        ok("has customers", len(customers) > 0)
        assert len(customers) > 0
        cid = customers[0]["id"]
    else:
        # Might be paginated
        items = customers.get("items") or customers.get("data") or customers.get("customers") or []
        ok("has customers", len(items) > 0)
        assert len(items) > 0
        cid = items[0]["id"]

    r = req.get(f"{BASE}/api/customers/{cid}", cookies=cookies)
    customer = r.json()
    apps = customer.get("applications", [])
    ok("customer has apps", len(apps) > 0)

    aid = apps[0]["id"]

    # 4. List materials (should have tree)
    r = req.get(f"{BASE}/api/applications/{aid}/materials/", cookies=cookies)
    ok("list materials", r.status_code == 200)
    data = r.json()
    ok("materials has items", "items" in data)
    ok("materials has tree", "tree" in data)
    print(f"  tree: {json.dumps(data.get('tree', []), ensure_ascii=False)[:200]}")

    # 5. Upload a new material
    files = {"file": ("test_upload.pdf", b"%PDF-1.4 test content", "application/pdf")}
    r = req.post(f"{BASE}/api/applications/{aid}/materials/", data={"category": "身份证明"}, files=files, cookies=cookies)
    ok("upload returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    mat = r.json()
    ok("upload has id", mat.get("id") is not None)
    ok("upload has file_path", mat.get("file_path") is not None)
    print(f"  stored path: {mat.get('file_path')}")
    mat_id = mat["id"]

    # 6. Download the file
    r = req.get(f"{BASE}/api/applications/{aid}/materials/file/{mat_id}", cookies=cookies)
    ok("download returns 200", r.status_code == 200)
    ok("download content matches", r.content == b"%PDF-1.4 test content")
    ok("download has Content-Disposition", "Content-Disposition" in r.headers)

    # 7. Browse file tree
    r = req.get(f"{BASE}/api/applications/{aid}/materials/browse", cookies=cookies)
    ok("browse returns 200", r.status_code == 200)
    browse = r.json()
    ok("browse has customer_dir", "customer_dir" in browse)
    ok("browse has tree", "tree" in browse)

    # 8. Delete the material
    r = req.delete(f"{BASE}/api/applications/{aid}/materials/{mat_id}", cookies=cookies)
    ok("delete returns 200", r.status_code == 200)
    # Verify deleted
    r = req.get(f"{BASE}/api/applications/{aid}/materials/file/{mat_id}", cookies=cookies)
    ok("download after delete returns 404", r.status_code == 404)

finally:
    proc.terminate()
    proc.wait()

print(f"\nResults: {passed} passed, {failed} failed out of {passed+failed} tests")
sys.exit(1 if failed else 0)
