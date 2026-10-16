"""Gera os ícones do PWA em app/static/icons (rodar só quando quiser mudar o desenho).

Uso: pip install pillow && python scripts/gerar_icones.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
FUNDO = (13, 14, 18)
CORES = [(108, 200, 255), (255, 200, 97), (111, 227, 154), (179, 161, 255)]  # as 4 áreas


def desenhar(tam: int, margem: float) -> Image.Image:
	"""Quatro barras com as cores das áreas e um "check" na primeira."""
	s = 4  # desenha maior e reduz (bordas suaves)
	n = tam * s
	img = Image.new("RGB", (n, n), FUNDO)
	d = ImageDraw.Draw(img)
	m = n * margem
	area = n - 2 * m
	alt = area / 4 * 0.62
	gap = (area - 4 * alt) / 3
	for i, cor in enumerate(CORES):
		y = m + i * (alt + gap)
		larg = area * (1.0, 0.78, 0.9, 0.6)[i]
		x0 = m + alt * 1.25
		d.rounded_rectangle([x0, y, m + larg, y + alt], radius=alt / 2, fill=cor)
		d.ellipse([m, y, m + alt, y + alt], outline=cor, width=int(alt * 0.16))
	# check na primeira bolinha
	y = m
	pts = [(m + alt * 0.27, y + alt * 0.52), (m + alt * 0.44, y + alt * 0.7), (m + alt * 0.75, y + alt * 0.32)]
	d.ellipse([m, y, m + alt, y + alt], fill=CORES[0])
	d.line(pts, fill=FUNDO, width=int(alt * 0.14), joint="curve")
	return img.resize((tam, tam), Image.LANCZOS)


def main() -> None:
	DESTINO.mkdir(parents=True, exist_ok=True)
	desenhar(192, 0.16).save(DESTINO / "icon-192.png")
	desenhar(512, 0.16).save(DESTINO / "icon-512.png")
	desenhar(512, 0.26).save(DESTINO / "icon-maskable-512.png")  # área segura do Android
	desenhar(180, 0.16).save(DESTINO / "apple-touch-icon.png")
	print("Ícones gerados em", DESTINO)


if __name__ == "__main__":
	main()
