"""md_to_docx converter: handles synthetic markdown and the real trader-guide."""
import importlib.util
import sys

import pytest

from conftest import PROJECT_ROOT

docx = pytest.importorskip("docx")  # python-docx

spec = importlib.util.spec_from_file_location(
    "md_to_docx_mod", PROJECT_ROOT / "scripts" / "md_to_docx.py")
md_mod = importlib.util.module_from_spec(spec)
sys.modules["md_to_docx_mod"] = md_mod
spec.loader.exec_module(md_mod)

SAMPLE_MD = """# Заголовок 1

Обычный абзац с **жирным** и `кодом`.

## Заголовок 2

- пункт раз
- пункт два

1. первый
2. второй

| Колонка A | Колонка B |
|---|---|
| значение 1 | значение 2 |
| значение 3 | значение 4 |

```python
print("hello")
```

---
"""


def test_convert_sample_markdown(tmp_path):
    out = tmp_path / "sample.docx"
    result = md_mod.md_to_docx(SAMPLE_MD, out_path=out)
    assert result == out and out.exists() and out.stat().st_size > 0

    document = docx.Document(str(out))
    texts = [p.text for p in document.paragraphs]
    assert any("Заголовок 1" in t for t in texts)
    assert any("жирным" in t for t in texts)
    assert any("пункт раз" in t for t in texts)
    assert any("print" in t for t in texts)          # code block content
    assert len(document.tables) == 1                  # markdown table -> docx table
    table = document.tables[0]
    assert table.rows[0].cells[0].text.strip() == "Колонка A"
    assert table.rows[2].cells[1].text.strip() == "значение 4"


def test_convert_real_trader_guide(tmp_path):
    """The converter must survive the actual reference document."""
    src = PROJECT_ROOT / "references" / "trader-guide.md"
    if not src.exists():
        pytest.skip("references/trader-guide.md not present")
    md_text = src.read_text(encoding="utf-8")
    out = tmp_path / "guide.docx"
    md_mod.md_to_docx(md_text, out_path=out)
    assert out.stat().st_size > 5000
    document = docx.Document(str(out))
    assert len(document.paragraphs) > 20


def test_default_output_path_is_project_reference():
    assert md_mod.DOCX_PATH == PROJECT_ROOT / "references" / "trader-guide.docx"
