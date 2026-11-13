"""Sync make_files.py embedded sources with live (fixed) files."""
base = 'clawhunt/pipeline/tasks/3006/'
mf = open(base + 'make_files.py', encoding='utf-8').read()

sections = [
    ('# ---------- app/main.py ----------', 'app/main.py'),
    ('# ---------- app/permissions.py ----------', 'app/permissions.py'),
    ('# ---------- app/tenant.py ----------', 'app/tenant.py'),
    ('# ---------- tests/conftest.py ----------', 'tests/conftest.py'),
    ('# ---------- tests/test_front_desk.py ----------', 'tests/test_front_desk.py'),
]
TQ = "'''"


def replace_section(src, header, new_text):
    h = src.index(header)
    q1 = src.index(TQ + '\\\n', h) + len(TQ) + 2
    q2 = src.index(TQ + '\n', q1)
    return src[:q1] + new_text + src[q2:]


for header, path in sections:
    content = open(base + path, encoding='utf-8').read()
    mf = replace_section(mf, header, content)

open(base + 'make_files.py', 'w', encoding='utf-8', newline='\n').write(mf)
print('make_files.py synced')
