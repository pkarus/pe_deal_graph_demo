"""R18 independent G3 name diff: ONTOLOGY.md vs pe_deal_graph/model/core.py (AST only, no engine)."""
import ast, re, sys, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
md = (root / "ONTOLOGY.md").read_text()
tree = ast.parse((root / "pe_deal_graph/model/core.py").read_text())

def is_model_call(n, attr):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "model")

code_concepts, code_names = set(), set()
for n in ast.walk(tree):
    if isinstance(n, ast.Assign) and len(n.targets) == 1:
        t, v = n.targets[0], n.value
        if isinstance(t, ast.Name) and is_model_call(v, "Concept"):
            code_concepts.add(v.args[0].value)
            code_names.add(v.args[0].value)
        elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and (
                is_model_call(v, "Property") or is_model_call(v, "Relationship")):
            code_names.add(f"{t.value.id}.{t.attr}")
        elif isinstance(t, ast.Name):
            code_names.add(t.id)

def section(title_re):
    m = re.search(rf"^## {title_re}.*?$(.*?)(?=^## |\Z)", md, re.M | re.S)
    return m.group(1)

doc_concepts = set(re.findall(r"^\| `([A-Za-z0-9_]+)` \|", section(r"2\. Concept glossary"), re.M))
contract = set(re.findall(r"^\| `([A-Za-z0-9_.]+)` \|", section(r"5\. Interface contract"), re.M))
fails = 0
def diff(label, a, b, an, bn):
    global fails
    print(f"{label}: {an}={len(a)} {bn}={len(b)} only_in_{an}={sorted(a-b)} only_in_{bn}={sorted(b-a)}")
    if a != b: fails += 1
diff("concepts", doc_concepts, code_concepts, "doc", "code")
missing = contract - code_names
print(f"contract names in doc={len(contract)} unresolved_in_code={sorted(missing)}")
if len(contract) != 101 or missing: fails += 1
print("G3 NAMES", "FAIL" if fails else "PASS")
sys.exit(1 if fails else 0)
