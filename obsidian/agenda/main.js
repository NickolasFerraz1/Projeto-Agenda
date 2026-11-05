/* Plugin "Agenda" para o Obsidian: envia a nota de planejamento para o app Projeto Agenda.
 *
 * - Botão na barra lateral (ícone de calendário), comando "Enviar nota para a Agenda"
 *   (dá para atalhar em Configurações > Teclas de atalho) e item no menu da nota.
 * - Mostra a prévia (o que será criado/atualizado) e só importa depois de confirmar.
 * - Usa a mesma API da tela "Importar plano": POST /api/planos/previa e /api/planos/importar.
 * - Acrescenta `obsidian:` no cabeçalho do que é enviado (a nota não muda), para o projeto
 *   no app ganhar o link "Planejamento (Obsidian)" de volta para esta nota.
 * A conexão é a mesma do app: pelo Tailscale (o computador precisa estar com ele ligado).
 */
const { Plugin, PluginSettingTab, Setting, Modal, Notice, requestUrl, TFile } = require("obsidian");

const PADRAO = { url: "https://magicmirror.tailc1dcbd.ts.net" };

function mensagem(e) {
	const m = String((e && e.message) || e);
	if (/net::|ERR_|fetch failed|Failed to fetch|ENOTFOUND|ECONN|ETIMEDOUT|timed out|getaddrinfo/i.test(m)) {
		return "Não consegui falar com a Agenda. O Tailscale está ligado neste computador?";
	}
	return "Agenda: " + m;
}

function detalhe(json) {
	const d = json && json.detail;
	if (!d) return null;
	if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
	return String(d);
}

class AgendaPlugin extends Plugin {
	async onload() {
		await this.carregarConfig();
		this.addRibbonIcon("calendar-plus", "Enviar para a Agenda", () => this.enviar());
		this.addCommand({
			id: "enviar-para-agenda",
			name: "Enviar nota para a Agenda",
			checkCallback: (verificando) => {
				const f = this.app.workspace.getActiveFile();
				if (!f || f.extension !== "md") return false;
				if (!verificando) this.enviar(f);
				return true;
			},
		});
		this.registerEvent(
			this.app.workspace.on("file-menu", (menu, file) => {
				if (file instanceof TFile && file.extension === "md") {
					menu.addItem((i) => i.setTitle("Enviar para a Agenda").setIcon("calendar-plus").onClick(() => this.enviar(file)));
				}
			})
		);
		this.addSettingTab(new AgendaConfig(this.app, this));
	}

	async carregarConfig() {
		this.config = Object.assign({}, PADRAO, await this.loadData());
	}

	async salvarConfig() {
		await this.saveData(this.config);
	}

	base() {
		return this.config.url.trim().replace(/\/+$/, "");
	}

	linkObsidian(file) {
		const vault = encodeURIComponent(this.app.vault.getName());
		return `obsidian://open?vault=${vault}&file=${encodeURIComponent(file.path.replace(/\.md$/, ""))}`;
	}

	/** Põe `obsidian:` no cabeçalho do texto enviado (se ainda não tiver). */
	comLink(texto, file) {
		const t = texto.replace(/\r\n/g, "\n");
		if (!t.startsWith("---\n")) return t;  // sem cabeçalho: o importador explica o formato
		const fim = t.indexOf("\n---", 4);
		const cabecalho = fim > 0 ? t.slice(0, fim) : t;
		if (/^obsidian\s*:/m.test(cabecalho)) return t;
		return `---\nobsidian: ${this.linkObsidian(file)}\n` + t.slice(4);
	}

	async chamar(rota, opcoes = {}) {
		const r = await requestUrl({ url: this.base() + rota, throw: false, ...opcoes });
		let json = null;
		try { json = r.json; } catch (_) { /* resposta sem JSON */ }
		if (r.status >= 400) throw new Error(detalhe(json) || `a Agenda respondeu ${r.status}`);
		return json;
	}

	postar(rota, texto) {
		return this.chamar(rota, { method: "POST", contentType: "application/json", body: JSON.stringify({ texto }) });
	}

	async enviar(file) {
		file = file || this.app.workspace.getActiveFile();
		if (!file || file.extension !== "md") {
			new Notice("Abra a nota do planejamento primeiro.");
			return;
		}
		const texto = this.comLink(await this.app.vault.read(file), file);
		const aviso = new Notice("Agenda: preparando a prévia…", 0);
		try {
			const rel = await this.postar("/api/planos/previa", texto);
			aviso.hide();
			new Previa(this.app, this, texto, rel).open();
		} catch (e) {
			aviso.hide();
			new Notice(mensagem(e), 10000);
		}
	}
}

const ROTULO = { novo: "novo", atualizado: "atualizado", igual: "" };
// [singular, plural, feminino?]
const NOMES = { projeto: ["projeto", "projetos", false], etapa: ["etapa", "etapas", true], item: ["tarefa", "tarefas", true] };

class Previa extends Modal {
	constructor(app, plugin, texto, rel) {
		super(app);
		this.plugin = plugin;
		this.texto = texto;
		this.rel = rel;
	}

	resumo() {
		const c = this.rel.contagem || {};
		const partes = [];
		for (const tipo of ["projeto", "etapa", "item"]) {
			for (const acao of ["novo", "atualizado"]) {
				const n = c[`${tipo}_${acao}`];
				if (!n) continue;
				const [um, varios, fem] = NOMES[tipo];
				const adj = (fem ? acao.replace(/o$/, "a") : acao) + (n === 1 ? "" : "s");
				partes.push(`${n} ${n === 1 ? um : varios} ${adj}`);
			}
		}
		return partes.length ? partes.join(" · ") : "Nada mudou: a Agenda já está igual a esta nota.";
	}

	onOpen() {
		const { contentEl } = this;
		contentEl.addClass("agenda-previa");
		const raiz = (this.rel.linhas || []).find((l) => l[1] === "projeto");
		contentEl.createEl("h3", { text: `Enviar “${raiz ? raiz[2] : "plano"}” para a Agenda` });
		contentEl.createEl("p", { text: this.resumo(), cls: "agenda-resumo" });
		for (const a of this.rel.avisos || []) contentEl.createEl("p", { text: "⚠ " + a, cls: "agenda-aviso" });

		const lista = contentEl.createEl("ul", { cls: "agenda-arvore" });
		for (const [nivel, tipo, nome, acao, feito] of this.rel.linhas || []) {
			const li = lista.createEl("li", { cls: `agenda-${tipo} ${feito ? "agenda-feito" : ""}` });
			li.style.paddingLeft = `${(nivel - 1) * 16}px`;
			li.createSpan({ text: (tipo === "item" ? (feito ? "✓ " : "○ ") : "▸ ") + nome });
			if (ROTULO[acao]) li.createSpan({ text: ROTULO[acao], cls: `agenda-acao agenda-${acao}` });
		}
		if ((this.rel.mantidos || []).length) {
			contentEl.createEl("p", { text: `${this.rel.mantidos.length} coisa(s) existem no app e não nesta nota: ficam como estão.`, cls: "agenda-dica" });
		}

		const botoes = contentEl.createDiv({ cls: "agenda-botoes" });
		const importar = botoes.createEl("button", { text: "Importar", cls: "mod-cta" });
		botoes.createEl("button", { text: "Cancelar" }).onclick = () => this.close();
		importar.onclick = async () => {
			importar.disabled = true;
			importar.setText("Importando…");
			try {
				const rel = await this.plugin.postar("/api/planos/importar", this.texto);
				this.close();
				const frag = createFragment((f) => {
					f.appendText(`“${raiz ? raiz[2] : "Plano"}” na Agenda. `);
					if (rel.projeto_id) {
						const a = f.createEl("a", { text: "Abrir no app", href: `${this.plugin.base()}/projetos/${rel.projeto_id}` });
						a.onclick = (ev) => { ev.preventDefault(); window.open(a.href); };
					}
				});
				new Notice(frag, 10000);
			} catch (e) {
				importar.disabled = false;
				importar.setText("Importar");
				new Notice(mensagem(e), 10000);
			}
		};
	}

	onClose() {
		this.contentEl.empty();
	}
}

class AgendaConfig extends PluginSettingTab {
	constructor(app, plugin) {
		super(app, plugin);
		this.plugin = plugin;
	}

	display() {
		const { containerEl } = this;
		containerEl.empty();
		new Setting(containerEl)
			.setName("Endereço do app")
			.setDesc("O mesmo que você abre no navegador (pelo Tailscale).")
			.addText((t) => t.setPlaceholder(PADRAO.url).setValue(this.plugin.config.url).onChange(async (v) => {
				this.plugin.config.url = v || PADRAO.url;
				await this.plugin.salvarConfig();
			}));
		new Setting(containerEl)
			.setName("Testar conexão")
			.addButton((b) => b.setButtonText("Testar").onClick(async () => {
				try {
					const s = await this.plugin.chamar("/api/saude");
					new Notice(s && s.ok ? "Agenda: conexão ok." : "Agenda: respondeu, mas algo está estranho.");
				} catch (e) {
					new Notice(mensagem(e), 10000);
				}
			}));
	}
}

module.exports = AgendaPlugin;
