"""Mutation verification for 3006 (reviewer-style): kill each defense, expect failures.

No pytest plugins assumed: plain `pytest -q`, parse result line.
"""
import os
import re
import subprocess

D = r'clawhunt/pipeline/tasks/3006'


def run_tests():
    env = dict(os.environ, APP_ENV='test', PYTHONDONTWRITEBYTECODE='1')
    r = subprocess.run([os.sys.executable, '-m', 'pytest', 'tests/', '-q', '--no-header'],
                       cwd=D, capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    f = re.search(r'(\d+) failed', out)
    p = re.search(r'(\d+) passed', out)
    if not f and not p:
        return None, out.strip().splitlines()[-3:]
    return (int(f.group(1)) if f else 0), None


def mutated(rel, old, new):
    """Temporarily mutate file, return (failed_count, error_lines)."""
    return mutated_dual(rel, old, new, rel, old, new)


def mutated_dual(rel1, old1, new1, rel2, old2, new2):
    """Temporarily mutate one or two files (two patterns in same file supported)."""
    same = rel1 == rel2
    p1 = os.path.join(D, rel1)
    p2 = os.path.join(D, rel2)
    o1 = open(p1, encoding='utf-8').read()
    o2 = o1 if same else open(p2, encoding='utf-8').read()
    if old1 not in o1 or old2 not in o2:
        return None, [f'MUTATION TARGET NOT FOUND: {old1[:40]!r} / {old2[:40]!r}']
    m1 = o1.replace(old1, new1)
    m2 = m1.replace(old2, new2) if same else o2.replace(old2, new2)
    try:
        open(p1, 'w', encoding='utf-8', newline='\n').write(m2 if same else m1)
        if not same:
            open(p2, 'w', encoding='utf-8', newline='\n').write(m2)
        return run_tests()
    finally:
        open(p1, 'w', encoding='utf-8', newline='\n').write(o1)
        if not same:
            open(p2, 'w', encoding='utf-8', newline='\n').write(o2)


failed, err = run_tests()
if err:
    print('BASELINE ERROR:', err)
    raise SystemExit(1)
print(f'== baseline: {failed} failed (expect 0) ==')

mutations = [
    ('app/permissions.py',
     'if entry is None:',
     'if False:',
     'deny-check killed -> deny tests must fail'),
    ('app/permissions.py',
     'if pctx.scope == "site" and r["site_id"] != ctx.site_id:',
     'if False and pctx.scope == "site" and r["site_id"] != ctx.site_id:',
     'site data-scope killed -> records test must fail'),
    ('app/permissions.py',
     'if pctx.scope == "self" and r["owner_id"] != ctx.user_id:',
     'if False and pctx.scope == "self" and r["owner_id"] != ctx.user_id:',
     'self data-scope killed -> ai.assistant records test must fail'),
]

# Dual-guard mutations: each guard alone is defense-in-depth (the other catches),
# so kill both to prove the site-B tests exercise the pair.
DUAL = [
    ('app/tenant.py',
     'if requested_site not in allowed_sites:',
     'if False:',
     'app/tenant.py',
     'if ctx.site_id not in allowed_sites:',
     'if False:',
     'BOTH site guards killed -> site-B tests must fail'),
    ('app/tenant.py',
     'if requested_site and requested_site != ctx.site_id:',
     'if requested_site and False:',
     'app/tenant.py',
     'if ctx.site_id not in allowed_sites:',
     'if False:',
     'switch-branch disabled + membership guard killed -> site-B tests must fail'),
]

all_ok = True
for rel, old, new, desc in mutations:
    failed, err = mutated(rel, old, new)
    if err:
        print('ERR', desc, err)
        all_ok = False
    elif failed > 0:
        print(f'MUTATED ok: {desc} -> {failed} failed (caught)')
    else:
        print(f'MUTATION SURVIVED: {desc} -> 0 failed (fake positive!)')
        all_ok = False

for rel1, old1, new1, rel2, old2, new2, desc in DUAL:
    failed, err = mutated_dual(rel1, old1, new1, rel2, old2, new2)
    if err:
        print('ERR', desc, err)
        all_ok = False
    elif failed > 0:
        print(f'MUTATED ok: {desc} -> {failed} failed (caught)')
    else:
        print(f'MUTATION SURVIVED: {desc} -> 0 failed (fake positive!)')
        all_ok = False

print('ALL MUTATIONS CAUGHT' if all_ok else 'SOME MUTATIONS SURVIVED')
