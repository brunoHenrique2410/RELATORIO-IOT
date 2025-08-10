# streamlit_app.py
import streamlit as st
from PIL import Image
import io
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from datetime import date

st.set_page_config(page_title="Gerador Relatório Fotográfico - CEF Wi-Fi", layout="wide")

# -----------------------
# Configurações de mapeamento
# -----------------------
# Cada chave representa um "campo" lógico do relatório.
# Cada valor é uma lista de palavras/fragmentos que, se encontradas
# no nome do arquivo enviado, fazem o arquivo ser atribuído a este campo.
SLOTS_KEYWORDS = {
    "rack": ["rack"],
    "local_ap": ["local", "ap_instalado", "apficou", "onde_ap"],
    "panoramica": ["panoramica", "panorâmica", "panoramico", "panoram"],
    "area_autoatendimento": ["autoatendimento", "auto_atendimento", "autoatend"],
    "equipamento": ["equipamento", "device", "equip"],
    "mac": ["mac"],
    "serial": ["serial"],
    "mac_serial": ["mac_serial", "macserial"],
    "teste_velocidade": ["speedtest", "velocidade", "teste_link", "teste_velocidade"],
    "tela_conexao": ["tela_conexao", "tela_conexão", "telawifi", "tela_conexao_wifi"],
    "teste_mtu": ["mtu", "banda", "teste_mtu"],
    "portal_login": ["portal", "captive", "captcha", "captivo", "portal_login"],
    "checklist": ["checklist"],
    "rat": ["rat"],
}

# Ordem usada na geração do PDF (apresentação visual)
PDF_IMAGE_ORDER = [
    ("RACK", "rack"),
    ("LOCAL ONDE O AP FICOU INSTALADO", "local_ap"),
    ("FOTO PANORÂMICA DA SALA", "panoramica"),
    ("ÁREA DE AUTOATENDIMENTO", "area_autoatendimento"),
    ("EQUIPAMENTO", "equipamento"),
    ("MAC / SERIAL DO EQUIPAMENTO", "mac_serial"),  # prefer mac_serial
    ("MAC (separado)", "mac"),
    ("SERIAL (separado)", "serial"),
    ("PRINT TESTE DO LINK (SpeedTest)", "teste_velocidade"),
    ("PRINT DA TELA DE CONEXÃO WIFI (CLIENTES_CAIXA)", "tela_conexao"),
    ("PRINT DO TESTE WI-FI BANDA E MTU 1500 BYTES", "teste_mtu"),
    ("PRINTS TELA LOGIN CAPTIVE PORTAL (ANTES/APÓS)", "portal_login"),
    ("CHECKLIST PREENCHIDO ASSINADO", "checklist"),
    ("RAT PREENCHIDA ASSINADA", "rat"),
]

# Requisitos mínimos por tipo
REQUIRED_BY_TYPE = {
    "produtiva": ["rack", "local_ap", "panoramica", "area_autoatendimento",
                  "equipamento", ("mac_serial", "mac"), "teste_velocidade",
                  "tela_conexao", "teste_mtu", "portal_login", "checklist", "rat"],
    "improdutiva": ["rack", "local_ap", "area_autoatendimento",
                    "equipamento", ("mac_serial", "mac", "serial"), "teste_velocidade", "checklist", "rat"],
}

# -----------------------
# Helper functions
# -----------------------
def normalize_filename(fname: str) -> str:
    fname = fname.lower()
    fname = re.sub(r"\s+", "_", fname)
    fname = re.sub(r"[^\w_]", "_", fname)  # remove caracteres estranhos
    return fname

def map_uploaded_files(uploaded_files):
    """
    Recebe lista de streamlit uploaded_files e retorna um dict:
    slot_name -> file_bytes (BytesIO)
    Se houver múltiplos arquivos para o mesmo slot, mantém o primeiro.
    """
    mapped = {}
    for f in uploaded_files:
        name = normalize_filename(f.name)
        content = f.read()
        # tenta encontrar um slot para esse arquivo
        assigned = False
        for slot, keywords in SLOTS_KEYWORDS.items():
            for kw in keywords:
                if kw in name:
                    if slot not in mapped:
                        mapped[slot] = io.BytesIO(content)
                    assigned = True
                    break
            if assigned:
                break
        # se não casou com nenhuma palavra-chave, não atribui (pode aparecer como "não mapeado")
    return mapped

def check_requirements(mapped, tipo):
    """
    Retorna (ok: bool, missing: list)
    missing é lista de strings descrevendo slots ausentes.
    Notar que em REQUIRED_BY_TYPE existem tuplas para aceitar alternativas.
    """
    required = REQUIRED_BY_TYPE[tipo]
    missing = []
    for req in required:
        if isinstance(req, tuple):
            # qualquer um presente satisfaz
            if not any((r in mapped) for r in req):
                missing.append(" ou ".join(req))
        else:
            if req not in mapped:
                missing.append(req)
    return (len(missing) == 0, missing)

def pil_image_from_bytes(io_bytes):
    io_bytes.seek(0)
    return Image.open(io_bytes)

def add_image_to_canvas(c, pil_img, x, y, max_w, max_h):
    """
    Adiciona uma imagem PIL ao canvas (reportlab) mantendo aspecto.
    (x, y) = canto inferior esquerdo onde a imagem será colocada.
    max_w, max_h em pontos (1 pt ~= 1/72 inch).
    """
    img_w, img_h = pil_img.size
    # converter px -> points: assumir 72 dpi se não especificado, mas PIL size já dá px.
    # Para dimensionamento proporcional, usar relação de aspecto
    ratio = min(max_w / img_w, max_h / img_h, 1.0)
    draw_w = img_w * ratio
    draw_h = img_h * ratio
    # converter PIL image para ImageReader
    img_buf = io.BytesIO()
    pil_img.save(img_buf, format="PNG")
    img_buf.seek(0)
    c.drawImage(ImageReader(img_buf), x, y + (max_h - draw_h), width=draw_w, height=draw_h, preserveAspectRatio=True, mask='auto')

# -----------------------
# UI
# -----------------------
st.title("Gerador de Relatório Fotográfico — CEF Wi-Fi")
st.markdown("Preencha os dados, faça upload das fotos (nomes detectados automaticamente) e gere o PDF.")

with st.form("form"):
    col1, col2 = st.columns([2,1])
    with col1:
        raw_chamado = st.text_input("Número do Chamado (pode colar texto, pegamos só o número):", placeholder="ex: 20250330762")
        # extrair apenas dígitos para uso no nome do arquivo
        match = re.search(r"\d+", raw_chamado or "")
        chamado_number = match.group(0) if match else ""
        if not chamado_number and raw_chamado:
            st.warning("Não foi possível extrair um número automático do que você digitou. Verifique.")
    with col2:
        data_inst = st.date_input("Data da Instalação:", value=date.today())
    tipo = st.selectbox("Tipo de Checklist:", ["produtiva", "improdutiva"])

    st.markdown("**Envie as fotos** (podem enviar várias ao mesmo tempo). Nomeie as imagens com palavras-chave para mapeamento automático — exemplos abaixo.")
    uploaded = st.file_uploader("Upload das fotos (jpg, png, pdf scan etc.) — múltiplos", accept_multiple_files=True, type=['jpg','jpeg','png','pdf'])

    st.markdown("---")
    st.form_submit_button("Mapear arquivos e validar")

# Se nenhum upload, salvamos lista vazia
uploaded = uploaded or []

# Mostra instruções sobre nomes
with st.expander("Sugestões de nomes de arquivos (recomendado) — clique para ver"):
    st.markdown("""
    Para que o sistema localize automaticamente cada foto, **nomeie os arquivos** com palavras-chave.
    Exemplos:
    - `rack.jpg`
    - `local_ap.jpg` ou `onde_ap_ficou.jpg`
    - `panoramica_sala.jpg`
    - `area_autoatendimento.jpg`
    - `equipamento.jpg`
    - `mac.jpg`  ou `mac_serial.jpg`
    - `serial.jpg`
    - `teste_speedtest.jpg` ou `teste_velocidade.jpg`
    - `tela_conexao_wifi.jpg`
    - `teste_mtu.jpg`
    - `portal_login_antes.jpg`, `portal_login_depois.jpg`
    - `checklist_assinado.jpg`
    - `rat_assinada.jpg`
    """)
    st.markdown("O app detecta fragmentos do nome (case-insensitive). Evite acentos e caracteres especiais se possível.")

# Mapeamento
mapped = map_uploaded_files(uploaded)

st.subheader("Arquivos mapeados automaticamente")
if mapped:
    for k,v in mapped.items():
        # v é BytesIO; não podemos mostrar todos, mas mostramos nome + size
        v.seek(0, io.SEEK_END)
        size_kb = v.tell()/1024
        v.seek(0)
        st.write(f"- **{k}**  — {size_kb:.1f} KB")
else:
    st.info("Nenhuma foto mapeada automaticamente ainda. Faça upload com nomes conforme sugestões acima.")

# Validação
ok, missing = check_requirements(mapped, tipo)
if ok:
    st.success(f"Todos os itens obrigatórios para checklist *{tipo}* estão presentes.")
else:
    st.error(f"Faltam itens obrigatórios para checklist *{tipo}*: {', '.join(missing)}")
    st.write("Você precisa enviar as fotos faltantes antes de gerar. Se for realmente necessário, marque a opção de forçar geração (não recomendado).")

force = st.checkbox("Forçar geração mesmo com pendências (não recomendado)")

# Botão de geração final (fora do form)
if st.button("Gerar PDF"):
    if not chamado_number:
        st.error("Por favor, digite o número do chamado (pelo menos um dígito) para nomear o arquivo.")
    elif not ok and not force:
        st.error("Relatório não gerado: faltam imagens obrigatórias. Se quiser prosseguir mesmo assim, marque 'Forçar geração'.")
    else:
        # Gera PDF em memória
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margin = 40
        y_pos = height - margin

        # Cabeçalho
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin, y_pos, "CHECKLIST – Implantação CEF Wi-Fi")
        y_pos -= 24

        c.setFont("Helvetica", 10)
        c.drawString(margin, y_pos, f"Nº Chamado: {chamado_number}")
        c.drawString(margin + 250, y_pos, f"Versão: 01")
        c.drawString(margin + 390, y_pos, f"Data instalação: {data_inst.strftime('%d/%m/%Y')}")
        y_pos -= 18

        c.drawString(margin, y_pos, "Integradora: TELEFONICA DATA S.A. / BRASIL S/A")
        y_pos -= 14
        c.drawString(margin, y_pos, "Contrato: TELEFONICA DATA - IOT BIG DATA MANUTENÇÃO")
        y_pos -= 22

        # Objetivo (parágrafo)
        text = c.beginText(margin, y_pos)
        text.setFont("Helvetica", 10)
        text.textLines("Objetivo\nEste documento detalha a instalação do produto de prateleira Wi-Fi nas dependências do cliente descrito e atesta a funcionalidade dos equipamentos.")
        c.drawText(text)
        y_pos = text.getY() - 12

        # Espaço antes das fotos
        y_pos -= 6

        # Adiciona as imagens em sequência definida por PDF_IMAGE_ORDER
        max_w = width - 2 * margin
        image_section_height = 220  # altura reservada por imagem
        for label, slot in PDF_IMAGE_ORDER:
            # se não couber verticalmente, cria nova página
            if y_pos - image_section_height < margin:
                c.showPage()
                y_pos = height - margin

            # desenha título
            c.setFont("Helvetica-Bold", 11)
            c.drawString(margin, y_pos, label)
            y_pos -= 16

            # decide qual arquivo usar para este slot (alguns slots têm alternativas)
            pil_img = None
            if slot in mapped:
                try:
                    pil_img = pil_image_from_bytes(mapped[slot])
                except Exception:
                    pil_img = None
            else:
                # tenta buscar por mac_serial se slot == mac_serial, ou combinação
                # (nada extra, já coberto acima)
                pass

            if pil_img:
                # garantir modo compatível
                if pil_img.mode not in ("RGB", "RGBA"):
                    pil_img = pil_img.convert("RGB")
                add_image_to_canvas(c, pil_img, margin, y_pos - image_section_height + 8, max_w, image_section_height - 24)
                y_pos -= image_section_height
            else:
                # escreve caixa de "imagem não fornecida"
                c.setFont("Helvetica-Oblique", 9)
                c.rect(margin, y_pos - image_section_height + 8, max_w, image_section_height - 24)
                c.drawString(margin + 8, y_pos - image_section_height + 18, "Imagem não fornecida para este campo.")
                y_pos -= image_section_height

            y_pos -= 6  # espaço entre blocos

        # Conclusão
        if y_pos - 80 < margin:
            c.showPage()
            y_pos = height - margin
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y_pos, "Conclusão")
        y_pos -= 16
        c.setFont("Helvetica", 10)
        text = c.beginText(margin, y_pos)
        text.textLines("Atividade conforme demonstrado anteriormente.\nRealizado o teste de velocidade do link (conforme prints anexados)."
                       "\nObs.: Os equipamentos descritos abaixo ficaram instalados na agência.")
        c.drawText(text)

        # finaliza
        c.showPage()
        c.save()

        buffer.seek(0)
        pdf_bytes = buffer.read()

        filename = f"{chamado_number}.pdf"
        st.success("PDF gerado com sucesso.")
        st.download_button("Clique para baixar o PDF", data=pdf_bytes, file_name=filename, mime="application/pdf")
