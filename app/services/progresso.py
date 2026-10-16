"""Progresso de projetos e itens, hierarquia de projetos e liberação sequencial.

Progresso automático (modo "itens") de um projeto = média do progresso dos filhos
(itens e subprojetos). Se todos os filhos têm peso (duração estimada), a média é
ponderada pela duração; senão, é a média simples. Itens cancelados e recorrentes
(hábitos) não entram na conta.
"""
import re
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models import Item, ProgressoModo, Projeto, StatusItem, StatusProjeto


def ordem_natural(texto: str) -> list:
	"""'Aula 2' < 'Aula 10' (compara os números pelo valor)."""
	return [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", texto or "")]


def chave_irmaos(obj) -> tuple:
	"""Ordem entre irmãos: campo `ordem`, depois o nome/título em ordem natural."""
	return (obj.ordem or 0, ordem_natural(getattr(obj, "nome", None) or getattr(obj, "titulo", "")), obj.id or 0)


def _pct_proprio(obj) -> float | None:
	"""Percentual dos modos que não dependem de filhos (manual e quantidade)."""
	if obj.progresso_modo == ProgressoModo.manual:
		return obj.progresso_manual
	if obj.progresso_modo == ProgressoModo.quantidade:
		if not obj.progresso_total:
			return None
		return round(min(100.0, 100.0 * (obj.progresso_atual or 0) / obj.progresso_total), 1)
	return None


def _pct_item(item: Item) -> float:
	"""Quanto um item conta para o projeto: concluído = 100; senão, o próprio progresso (ou 0)."""
	if item.status == StatusItem.concluido:
		return 100.0
	return _pct_proprio(item) or 0.0


@dataclass
class Arvore:
	"""Todos os projetos e itens carregados uma vez; cálculos com memória."""

	projetos: dict[int, Projeto]
	filhos: dict[int | None, list[Projeto]] = field(default_factory=dict)
	itens: dict[int, list[Item]] = field(default_factory=dict)
	_pct: dict[int, float | None] = field(default_factory=dict)
	_peso: dict[int, float | None] = field(default_factory=dict)
	_bloq: set[int] | None = None

	@classmethod
	def carregar(cls, session: Session) -> "Arvore":
		projetos = {p.id: p for p in session.exec(select(Projeto)).all()}
		arv = cls(projetos)
		for p in projetos.values():
			arv.filhos.setdefault(p.pai_id, []).append(p)
		for lista in arv.filhos.values():
			lista.sort(key=chave_irmaos)
		validos = session.exec(
			select(Item).where(Item.projeto_id.is_not(None), Item.status != StatusItem.cancelado, Item.recorrencia.is_(None))
		).all()
		for it in validos:
			arv.itens.setdefault(it.projeto_id, []).append(it)
		return arv

	# ---------- hierarquia ----------
	def caminho(self, projeto_id: int | None) -> list[Projeto]:
		"""Da raiz até o projeto (inclusive)."""
		cam, visto = [], set()
		while projeto_id is not None and projeto_id in self.projetos and projeto_id not in visto:
			visto.add(projeto_id)
			cam.append(self.projetos[projeto_id])
			projeto_id = self.projetos[projeto_id].pai_id
		return cam[::-1]

	def caminho_texto(self, projeto_id: int | None, sep: str = " › ") -> str:
		return sep.join(p.nome for p in self.caminho(projeto_id))

	def descendentes(self, projeto_id: int) -> set[int]:
		ids, pilha = set(), [projeto_id]
		while pilha:
			for f in self.filhos.get(pilha.pop(), []):
				if f.id not in ids:
					ids.add(f.id)
					pilha.append(f.id)
		return ids

	# ---------- progresso ----------
	def peso(self, projeto_id: int) -> float | None:
		"""Soma das durações do projeto, se todos os filhos tiverem duração; senão None."""
		if projeto_id in self._peso:
			return self._peso[projeto_id]
		self._peso[projeto_id] = None  # proteção contra ciclos
		pesos = [it.duracao_min for it in self.itens.get(projeto_id, [])]
		pesos += [self.peso(f.id) for f in self.filhos.get(projeto_id, [])]
		total = sum(pesos) if pesos and all(p for p in pesos) else None
		self._peso[projeto_id] = total
		return total

	def percentual(self, projeto_id: int) -> float | None:
		if projeto_id in self._pct:
			return self._pct[projeto_id]
		self._pct[projeto_id] = None  # proteção contra ciclos
		p = self.projetos[projeto_id]
		if p.progresso_modo != ProgressoModo.itens:
			pct = _pct_proprio(p)
		else:
			partes: list[tuple[float, float | None]] = [(_pct_item(it), it.duracao_min) for it in self.itens.get(projeto_id, [])]
			for f in self.filhos.get(projeto_id, []):
				fp = self.percentual(f.id)
				if fp is None and f.status == StatusProjeto.concluido:
					fp = 100.0
				if fp is not None:
					partes.append((fp, self.peso(f.id)))
			if not partes:
				pct = None
			elif all(w for _, w in partes):
				pct = round(sum(v * w for v, w in partes) / sum(w for _, w in partes), 1)
			else:
				pct = round(sum(v for v, _ in partes) / len(partes), 1)
		self._pct[projeto_id] = pct
		return pct

	def concluido(self, projeto_id: int) -> bool:
		p = self.projetos[projeto_id]
		return p.status == StatusProjeto.concluido or (self.percentual(projeto_id) or 0) >= 100

	# ---------- liberação sequencial ----------
	def bloqueados(self) -> set[int]:
		"""Projetos travados: num pai sequencial, só o 1º filho não concluído fica liberado.
		Os descendentes de um projeto travado também ficam travados."""
		if self._bloq is not None:
			return self._bloq
		travados: set[int] = set()
		for pai_id, filhos in self.filhos.items():
			if pai_id is None or not self.projetos.get(pai_id) or not self.projetos[pai_id].sequencial:
				continue
			liberou = False
			for f in filhos:
				if self.concluido(f.id):
					continue
				if liberou:
					travados.add(f.id)
				liberou = True
		for pid in list(travados):
			travados |= self.descendentes(pid)
		self._bloq = travados
		return travados

	def fora_de_foco(self) -> set[int]:
		"""Projetos cujos itens não devem aparecer nas pendências: travados ou pausados/arquivados
		(incluindo os descendentes destes)."""
		ids = self.bloqueados()
		for p in self.projetos.values():
			if p.status in (StatusProjeto.pausado, StatusProjeto.arquivado):
				ids |= {p.id} | self.descendentes(p.id)
		return ids


def percentual(obj, session: Session | None = None) -> float | None:
	"""Percentual 0–100 conforme o modo, ou None quando não se aplica."""
	if isinstance(obj, Projeto) and obj.progresso_modo == ProgressoModo.itens:
		if session is None or not obj.id:
			return None
		return Arvore.carregar(session).percentual(obj.id)
	return _pct_proprio(obj)
