"""Markdown das notas -> HTML seguro (HTML cru desativado; links abrem em outra aba)."""
from markdown_it import MarkdownIt

# "js-default": CommonMark + tabelas e tachado, sem HTML cru. breaks: Enter = quebra de linha.
_md = MarkdownIt("js-default", {"breaks": True})

_link_open_padrao = _md.renderer.rules.get("link_open")


def _link_open(tokens, idx, options, env):
	tokens[idx].attrSet("target", "_blank")
	tokens[idx].attrSet("rel", "noopener")
	return _md.renderer.renderToken(tokens, idx, options, env)


_md.renderer.rules["link_open"] = _link_open


def render(texto: str | None) -> str:
	return _md.render(texto) if texto else ""
