"""Small source-specific HTML adapters; all output remains unreviewed."""
from io import BytesIO
from bs4 import BeautifulSoup
from xml.etree import ElementTree


class Adapter:
    def __init__(self, names, expected, cues):
        self.names = names
        self.expected = expected
        self.cues = cues

    def extract(self, raw, url, document_type="html"):
        if document_type == "pdf":
            from pdfminer.high_level import extract_text
            pages = extract_text(BytesIO(raw)).split("\f")
            sections = [{"heading": f"Page {number}", "level": 1,
                         "content": [{"text": " ".join(page.split())}]}
                        for number, page in enumerate(pages, 1) if page.strip()]
            return self._result(sections, url)
        if document_type == "xml":
            root = ElementTree.fromstring(raw)
            sections = []
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1].lower()
                if tag in ("section", "article", "item", "entry"):
                    title = next((" ".join(t.itertext()).strip() for t in element if t.tag.rsplit("}", 1)[-1].lower() in ("title", "heading")), tag)
                    body = " ".join(" ".join(element.itertext()).split())
                    sections.append({"heading": title, "level": 1, "content": [{"text": body}]})
            if not sections:
                body = " ".join(" ".join(root.itertext()).split())
                sections = [{"heading": root.tag.rsplit("}", 1)[-1], "level": 1, "content": [{"text": body}]}] if body else []
            return self._result(sections, url)
        soup = BeautifulSoup(raw, "html.parser", from_encoding="utf-8")
        for element in soup(["script", "style", "noscript", "nav", "footer"]):
            element.decompose()
        root = soup.find("main") or soup.find("article") or soup.body or soup
        sections, current = [], None
        tags = ["h1", "h2", "h3", "h4", "p", "li", "table"]
        if self.names == "va":
            tags.append("va-table")
        for node in root.find_all(tags):
            if node.find_parent(["table", "li", "p", "h1", "h2", "h3", "h4"]) and node.name != "table":
                continue
            if node.name.startswith("h"):
                current = {"heading": node.get_text(" ", strip=True), "level": int(node.name[1]), "content": []}
                sections.append(current)
            elif current:
                if node.name == "va-table":
                    rows = [[cell.get_text(" ", strip=True) for cell in row.find_all("span", recursive=False)]
                            for row in node.find_all("va-table-row", recursive=False)]
                    current["content"].append({"table": rows})
                elif node.name == "table":
                    rows = [[cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])] for row in node.find_all("tr")]
                    current["content"].append({"table": rows})
                else:
                    value = node.get_text(" ", strip=True)
                    if value:
                        current["content"].append({"text": value})
        return self._result(sections, url)

    def _result(self, sections, url):
        headings = " ".join(s["heading"].lower() for s in sections)
        return {"adapter": self.names, "url": url, "sections": sections,
                "expected_sections": self.expected,
                "missing_expected_sections": [term for term in self.expected if term not in headings],
                "candidate_requirements": [{"locator": s["heading"], "text": item["text"]}
                    for s in sections for item in s["content"] if "text" in item and
                    any(word in item["text"].lower() for word in self.cues)]}


ADAPTERS = {
    "ssa": Adapter("ssa", [], ("eligible", "qualify", "must", "credit", "require")),
    "medicare": Adapter("medicare", [], ("eligible", "qualify", "must", "income", "resource", "require")),
    "va": Adapter("va", ["pension"], ("eligible", "must", "income", "net worth", "wartime", "require")),
    "hhs": Adapter("hhs", ["poverty"], ("guideline", "household", "alaska", "hawaii")),
    "statute": Adapter("statute", [], ("eligible", "entitled", "shall", "income", "pension")),
}
