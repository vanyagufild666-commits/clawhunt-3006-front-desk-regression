p = 'clawhunt/pipeline/tasks/3006/tests/test_front_desk.py'
t = open(p, encoding='utf-8').read()
old = 'r.json()["detail"]["error"] == "permission_denied"'
new = 'r.json()["error"] == "permission_denied"'
n = t.count(old)
t = t.replace(old, new)
open(p, 'w', encoding='utf-8', newline='\n').write(t)
print('replaced', n, 'detail-error accesses')
print('site_b_without_header present:', 'test_site_b_without_header' in t)
