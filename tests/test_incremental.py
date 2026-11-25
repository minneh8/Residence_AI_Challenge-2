# tests/test_incremental.py
"""Testes offline do download incremental e do classificador de LLM.

O Canvas é simulado com objetos falsos que têm id, updated_at e size reais,
get_current_user e get_modules. Os PDFs "baixados" são gerados com o PyMuPDF.
Nada acessa a rede nem o .env.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
import pytest  # noqa: E402

from src.agente_canvas import classificador_llm  # noqa: E402
from src.agente_canvas.catalogo import Catalogo, EstadoAluno  # noqa: E402
from src.agente_canvas.service import CanvasService  # noqa: E402

CURSO = 93527


# ------------------------------------------------------------------------------
# Canvas simulado
# ------------------------------------------------------------------------------
def pdf_bytes(texto: str, paginas: int = 2) -> bytes:
    doc = pymupdf.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"{texto} - pagina {i + 1}")
    dados = doc.tobytes()
    doc.close()
    return dados


class Interrompido(BaseException):
    """Simula uma interrupção (Ctrl+C, queda de energia) no meio do download."""


class ArquivoFalso:
    def __init__(self, canvas, fid, nome, updated_at, conteudo=None):
        self.canvas = canvas
        self.id = fid
        self.display_name = nome
        self.filename = nome
        self.updated_at = updated_at
        self.conteudo = conteudo if conteudo is not None else pdf_bytes(nome)
        self.size = len(self.conteudo)

    def download(self, destino):
        if self.id in self.canvas.interromper_em:
            raise Interrompido(f"interrompido em {self.display_name}")
        self.canvas.downloads.append(self.display_name)
        Path(destino).write_bytes(self.conteudo)


class CursoFalso:
    def __init__(self, canvas):
        self.canvas = canvas
        self.id = CURSO

    def get_files(self, sort=None, order=None):
        assert (sort, order) == ("updated_at", "desc")
        ordenados = sorted(self.canvas.arquivos, key=lambda a: a.updated_at, reverse=True)
        for a in ordenados:  # gerador: só "busca" o item quando a iteração chega nele
            self.canvas.listados.append(a.display_name)
            yield a

    def get_modules(self, include=None):
        return [
            SimpleNamespace(name=nome, items=[{"type": "File", "content_id": fid} for fid in ids])
            for nome, ids in self.canvas.modulos.items()
        ]

    def get_assignments(self):
        return []


class CanvasFalso:
    def __init__(self, user_id=1001):
        self.user_id = user_id
        self.arquivos: list[ArquivoFalso] = []
        self.modulos: dict[str, list[int]] = {}
        self.downloads: list[str] = []
        self.listados: list[str] = []
        self.interromper_em: set[int] = set()

    def get_current_user(self):
        return SimpleNamespace(id=self.user_id, name="Aluno Teste")

    def get_course(self, course_id):
        assert course_id == CURSO
        return CursoFalso(self)

    def adicionar(self, fid, nome, updated_at, modulo=None, conteudo=None):
        self.arquivos.append(ArquivoFalso(self, fid, nome, updated_at, conteudo))
        if modulo:
            self.modulos.setdefault(modulo, []).append(fid)

    def zerar_contadores(self):
        self.downloads.clear()
        self.listados.clear()


def llm_simulada(categoria="livros", confianca=0.9):
    chamadas = []

    def classificar(caminho, nome, modulo, paginas):
        chamadas.append(nome)
        return {"categoria": categoria, "origem": "llm",
                "confianca": confianca, "justificativa": "simulado"}

    classificar.chamadas = chamadas
    return classificar


def criar_service(tmp_path, canvas, llm=None):
    service = CanvasService(
        api_url="https://canvas.test", api_key="token_fake",
        raw_dir=str(tmp_path / "raw"), state_dir=str(tmp_path / "estado"),
        classificador_llm=llm or llm_simulada(),
    )
    service.canvas = canvas
    return service


@pytest.fixture
def canvas():
    c = CanvasFalso()
    c.adicionar(1, "aula01.pdf", "2026-09-01T10:00:00Z", "Slides de Aula")
    c.adicionar(2, "aula02.pdf", "2026-09-08T10:00:00Z", "Slides de Aula")
    c.adicionar(3, "lista_exercicios_01.pdf", "2026-10-01T10:00:00Z", "Atividade de Entrega")
    c.adicionar(4, "Material de Apoio GP.pdf", "2026-10-05T10:00:00Z")  # indefinido -> LLM
    c.adicionar(5, "template_relatorio.docx", "2026-10-06T10:00:00Z", "Trabalho do Curso")
    return c


def pasta_curso(tmp_path) -> Path:
    return tmp_path / "raw" / str(CURSO)


# ------------------------------------------------------------------------------
# Download incremental
# ------------------------------------------------------------------------------
def test_primeira_execucao_baixa_tudo(tmp_path, canvas):
    llm = llm_simulada("livros")
    service = criar_service(tmp_path, canvas, llm)
    r = service.sincronizar_curso(CURSO)

    assert sorted(r["novos"]) == ["Material de Apoio GP.pdf", "aula01.pdf",
                                  "aula02.pdf", "lista_exercicios_01.pdf"]
    assert r["pulados"] == ["template_relatorio.docx"]  # .docx fica fora
    assert r["estado_gravado"] and r["mudou"]
    pasta = pasta_curso(tmp_path)
    assert (pasta / "slides" / "aula01.pdf").is_file()
    assert (pasta / "listas" / "lista_exercicios_01.pdf").is_file()
    assert (pasta / "livros" / "Material de Apoio GP.pdf").is_file()
    assert not list(pasta.glob("*.part")) and not list(pasta.glob(".*.part"))
    assert llm.chamadas == ["Material de Apoio GP.pdf"]  # só o indefinido vai para a LLM

    cat = Catalogo(pasta)
    e = cat.get(4)
    assert e["categoria"] == "livros" and e["origem"] == "llm" and e["llm"]["confianca"] == 0.9
    a1 = cat.get(1)
    assert a1["caminho"] == "slides/aula01.pdf" and a1["modulo"] == "Slides de Aula"
    assert a1["paginas"] == 2 and a1["updated_at"] == "2026-09-01T10:00:00Z"
    assert a1["size"] == canvas.arquivos[0].size and a1["baixado_em"]

    estado = EstadoAluno(tmp_path / "estado", "1001").do_curso(CURSO)
    assert estado["ultimo_updated_at"] == "2026-10-06T10:00:00Z"
    assert estado["ultimo_file_id"] == "5"


def test_segunda_execucao_baixa_zero_e_para_no_primeiro(tmp_path, canvas):
    service = criar_service(tmp_path, canvas)
    service.sincronizar_curso(CURSO)
    canvas.zerar_contadores()

    r = service.sincronizar_curso(CURSO)
    assert canvas.downloads == []
    assert canvas.listados == ["template_relatorio.docx"]  # parou no primeiro item
    assert r["parou_em"] == "template_relatorio.docx"
    assert not r["mudou"] and r["estado_gravado"]


def test_arquivo_novo_baixa_so_ele(tmp_path, canvas):
    service = criar_service(tmp_path, canvas)
    service.sincronizar_curso(CURSO)
    canvas.zerar_contadores()

    canvas.adicionar(6, "aula03.pdf", "2026-11-01T10:00:00Z", "Slides de Aula")
    r = service.sincronizar_curso(CURSO)
    assert canvas.downloads == ["aula03.pdf"]
    assert r["novos"] == ["aula03.pdf"]
    assert canvas.listados == ["aula03.pdf", "template_relatorio.docx"]
    assert (pasta_curso(tmp_path) / "slides" / "aula03.pdf").is_file()


def test_arquivo_atualizado_baixa_de_novo_e_mantem_categoria(tmp_path, canvas):
    llm = llm_simulada("livros")
    service = criar_service(tmp_path, canvas, llm)
    service.sincronizar_curso(CURSO)
    canvas.zerar_contadores()

    material = canvas.arquivos[3]
    material.updated_at = "2026-11-10T10:00:00Z"
    material.conteudo = pdf_bytes("versao nova", paginas=3)
    r = service.sincronizar_curso(CURSO)

    assert canvas.downloads == ["Material de Apoio GP.pdf"]
    assert r["atualizados"] == ["Material de Apoio GP.pdf"]
    assert llm.chamadas == ["Material de Apoio GP.pdf"]  # mesmo nome: não reclassifica
    e = Catalogo(pasta_curso(tmp_path)).get(4)
    assert e["updated_at"] == "2026-11-10T10:00:00Z" and e["paginas"] == 3
    assert e["categoria"] == "livros"
    destino = pasta_curso(tmp_path) / "livros" / "Material de Apoio GP.pdf"
    assert destino.read_bytes() == material.conteudo


def test_arquivo_apagado_do_disco_baixa_de_novo(tmp_path, canvas):
    service = criar_service(tmp_path, canvas)
    service.sincronizar_curso(CURSO)
    canvas.zerar_contadores()

    (pasta_curso(tmp_path) / "slides" / "aula01.pdf").unlink()  # o mais antigo
    r = service.sincronizar_curso(CURSO)
    assert canvas.downloads == ["aula01.pdf"]
    assert r["recuperados"] == ["aula01.pdf"]
    assert (pasta_curso(tmp_path) / "slides" / "aula01.pdf").is_file()


def test_outro_aluno_so_registra(tmp_path, canvas):
    criar_service(tmp_path, canvas).sincronizar_curso(CURSO)
    canvas.zerar_contadores()

    canvas.user_id = 2002
    r = criar_service(tmp_path, canvas).sincronizar_curso(CURSO)
    assert canvas.downloads == []
    assert len(r["registrados"]) == 4 and not r["novos"]
    assert EstadoAluno(tmp_path / "estado", "2002").do_curso(CURSO) is not None


def test_execucao_interrompida_nao_grava_estado_e_retoma(tmp_path, canvas):
    service = criar_service(tmp_path, canvas)
    canvas.interromper_em = {2}  # ordem desc: docx, 4, 3, 2 (interrompe), 1
    with pytest.raises(Interrompido):
        service.sincronizar_curso(CURSO)
    assert canvas.downloads == ["Material de Apoio GP.pdf", "lista_exercicios_01.pdf"]
    assert EstadoAluno(tmp_path / "estado", "1001").do_curso(CURSO) is None
    assert not list(pasta_curso(tmp_path).glob(".*.part"))

    canvas.interromper_em = set()
    canvas.zerar_contadores()
    r = criar_service(tmp_path, canvas).sincronizar_curso(CURSO)
    assert sorted(canvas.downloads) == ["aula01.pdf", "aula02.pdf"]
    assert sorted(r["registrados"]) == ["Material de Apoio GP.pdf", "lista_exercicios_01.pdf"]
    assert r["estado_gravado"]


def test_falha_num_arquivo_nao_grava_estado(tmp_path, canvas):
    service = criar_service(tmp_path, canvas)
    original = canvas.arquivos[1].download
    canvas.arquivos[1].download = lambda destino: (_ for _ in ()).throw(OSError("disco cheio"))
    r = service.sincronizar_curso(CURSO)
    assert r["falhas"] == ["aula02.pdf"] and not r["estado_gravado"]

    canvas.arquivos[1].download = original
    canvas.zerar_contadores()
    r = service.sincronizar_curso(CURSO)
    assert canvas.downloads == ["aula02.pdf"] and r["estado_gravado"]


def test_bloqueado_para_o_aluno_nao_baixa_e_segura_o_estado(tmp_path, canvas):
    # Módulo não publicado: o Canvas lista o arquivo com locked_for_user e o
    # download dá 404. Não deve tentar baixar nem contar como falha.
    canvas.adicionar(8, "aula03.pdf", "2026-11-01T10:00:00Z", "Slides de Aula")
    canvas.arquivos[-1].locked_for_user = True
    service = criar_service(tmp_path, canvas)
    r = service.sincronizar_curso(CURSO)
    assert r["bloqueados"] == ["aula03.pdf"] and r["falhas"] == []
    assert "aula03.pdf" not in canvas.downloads and not r["estado_gravado"]

    canvas.arquivos[-1].locked_for_user = False  # professor publicou o módulo
    canvas.zerar_contadores()
    r = service.sincronizar_curso(CURSO)
    assert canvas.downloads == ["aula03.pdf"] and r["novos"] == ["aula03.pdf"]
    assert r["bloqueados"] == [] and r["estado_gravado"]


def test_migracao_de_pdfs_soltos_e_pastas_antigas_nao_baixa(tmp_path, canvas):
    pasta = pasta_curso(tmp_path)
    (pasta / "conteudo").mkdir(parents=True)
    (pasta / "listas").mkdir()
    (pasta / "aula01.pdf").write_bytes(pdf_bytes("aula01 local"))                 # solto
    (pasta / "conteudo" / "aula02.pdf").write_bytes(pdf_bytes("aula02 local"))    # Lucas
    (pasta / "listas" / "lista_exercicios_01.pdf").write_bytes(pdf_bytes("lista"))  # Lucas
    (pasta / "conteudo" / "Material de Apoio GP.pdf").write_bytes(pdf_bytes("apoio"))
    (pasta / "anotacoes_pessoais.pdf").write_bytes(pdf_bytes("sem Canvas"))     # sem par

    r = criar_service(tmp_path, canvas).sincronizar_curso(CURSO)
    assert canvas.downloads == []
    assert sorted(r["migrados"]) == ["Material de Apoio GP.pdf", "aula01.pdf",
                                     "aula02.pdf", "lista_exercicios_01.pdf"]
    assert (pasta / "slides" / "aula01.pdf").is_file()
    assert (pasta / "slides" / "aula02.pdf").is_file()
    assert (pasta / "listas" / "lista_exercicios_01.pdf").is_file()
    assert (pasta / "livros" / "Material de Apoio GP.pdf").is_file()
    assert not (pasta / "conteudo").exists()  # pasta antiga vazia removida
    assert (pasta / "anotacoes_pessoais.pdf").is_file()  # sem correspondência: fica
    e = Catalogo(pasta).get(1)
    assert e["baixado_em"] is None and e["migrado_em"]


def test_nome_repetido_com_outro_id_ganha_sufixo(tmp_path, canvas):
    canvas.adicionar(7, "aula01.pdf", "2026-11-05T10:00:00Z", "Slides de Aula")
    criar_service(tmp_path, canvas).sincronizar_curso(CURSO)
    pasta = pasta_curso(tmp_path)
    assert (pasta / "slides" / "aula01.pdf").is_file()
    assert (pasta / "slides" / "aula01_1.pdf").is_file()  # o mais antigo chega depois
    assert Catalogo(pasta).get(1)["nome_local"] == "aula01_1.pdf"


def test_completo_percorre_tudo(tmp_path, canvas):
    service = criar_service(tmp_path, canvas)
    service.sincronizar_curso(CURSO)
    canvas.zerar_contadores()
    r = service.sincronizar_curso(CURSO, completo=True)
    assert len(canvas.listados) == 5 and canvas.downloads == []
    assert len(r["registrados"]) == 4 and r["parou_em"] is None


# ------------------------------------------------------------------------------
# Classificador de LLM (cliente simulado)
# ------------------------------------------------------------------------------
class LLMFalsa:
    def __init__(self, conteudo=None, erro=None):
        self.conteudo, self.erro, self.mensagens = conteudo, erro, None

    def invoke(self, mensagens):
        self.mensagens = mensagens
        if self.erro:
            raise self.erro
        return SimpleNamespace(content=self.conteudo)


@pytest.fixture
def pdf_apoio(tmp_path):
    caminho = tmp_path / "apoio.pdf"
    caminho.write_bytes(pdf_bytes("Guia de gerenciamento de projetos", paginas=5))
    return caminho


def test_llm_json_valido(pdf_apoio):
    llm = LLMFalsa('{"categoria": "livros", "confianca": 0.85, "justificativa": "apostila longa"}')
    r = classificador_llm.classificar_llm(pdf_apoio, "Material de Apoio GP.pdf",
                                          None, 5, llm=llm)
    assert r == {"categoria": "livros", "origem": "llm", "confianca": 0.85,
                 "justificativa": "apostila longa"}
    texto_enviado = llm.mensagens[1].content
    assert "Material de Apoio GP.pdf" in texto_enviado and "pagina 3" in texto_enviado
    assert "pagina 4" not in texto_enviado  # só as 3 primeiras páginas


def test_llm_json_em_bloco_de_codigo(pdf_apoio):
    llm = LLMFalsa('```json\n{"categoria": "slides", "confianca": 0.7, "justificativa": "x"}\n```')
    r = classificador_llm.classificar_llm(pdf_apoio, "a.pdf", llm=llm)
    assert r["categoria"] == "slides" and r["origem"] == "llm"


@pytest.mark.parametrize("conteudo", [
    "não sei classificar",
    '{"categoria": "apostila", "confianca": 0.9, "justificativa": "x"}',  # fora do Literal
    '{"categoria": "livros", "confianca": 1.7, "justificativa": "x"}',    # fora de 0-1
    '{"categoria": "livros"}',                                             # campos faltando
])
def test_llm_json_invalido_vira_outros(pdf_apoio, conteudo):
    r = classificador_llm.classificar_llm(pdf_apoio, "a.pdf", llm=LLMFalsa(conteudo))
    assert r["categoria"] == "outros" and r["origem"] == "llm:json_invalido"


def test_llm_confianca_baixa_vira_outros(pdf_apoio):
    llm = LLMFalsa('{"categoria": "livros", "confianca": 0.4, "justificativa": "talvez"}')
    r = classificador_llm.classificar_llm(pdf_apoio, "a.pdf", llm=llm)
    assert r["categoria"] == "outros" and r["origem"] == "llm:confianca_baixa"
    assert r["confianca"] == 0.4


def test_llm_erro_da_api_sinaliza_erro(pdf_apoio):
    r = classificador_llm.classificar_llm(pdf_apoio, "a.pdf", llm=LLMFalsa(erro=RuntimeError("503")))
    assert r["categoria"] == "outros" and r["origem"] == "llm:erro_api"


def test_erro_da_api_nao_grava_no_catalogo_e_tenta_de_novo(tmp_path, canvas):
    def llm_com_erro(caminho, nome, modulo, paginas):
        return {"categoria": "outros", "origem": "llm:erro_api",
                "confianca": 0.0, "justificativa": "erro na chamada da LLM: RuntimeError"}

    r = criar_service(tmp_path, canvas, llm_com_erro).sincronizar_curso(CURSO)
    pasta = pasta_curso(tmp_path)
    assert r["pendentes_llm"] == ["Material de Apoio GP.pdf"] and not r["estado_gravado"]
    assert Catalogo(pasta).get(4) is None  # fora do catálogo
    assert not (pasta / "outros").exists() and not list(pasta.glob(".*.part"))
    assert len(r["novos"]) == 3  # os outros PDFs seguem normalmente

    canvas.zerar_contadores()
    llm = llm_simulada("livros")
    r = criar_service(tmp_path, canvas, llm).sincronizar_curso(CURSO)
    assert canvas.downloads == ["Material de Apoio GP.pdf"] and llm.chamadas == ["Material de Apoio GP.pdf"]
    assert Catalogo(pasta).get(4)["categoria"] == "livros" and r["estado_gravado"]


@pytest.mark.parametrize("origem", ["llm:json_invalido", "llm:confianca_baixa"])
def test_json_invalido_e_confianca_baixa_gravam_outros(tmp_path, canvas, origem):
    def llm_outros(caminho, nome, modulo, paginas):
        return {"categoria": "outros", "origem": origem, "confianca": 0.3, "justificativa": "x"}

    r = criar_service(tmp_path, canvas, llm_outros).sincronizar_curso(CURSO)
    e = Catalogo(pasta_curso(tmp_path)).get(4)
    assert e["categoria"] == "outros" and e["origem"] == origem and r["estado_gravado"]
    assert (pasta_curso(tmp_path) / "outros" / "Material de Apoio GP.pdf").is_file()


def test_texto_inicial_limita_caracteres(tmp_path):
    caminho = tmp_path / "longo.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        pagina = doc.new_page()
        pagina.insert_textbox(pymupdf.Rect(36, 36, 560, 800), "palavra " * 600, fontsize=6)
    doc.save(caminho)
    doc.close()
    assert len(classificador_llm.texto_inicial(caminho)) <= classificador_llm.MAX_CARACTERES_TEXTO
