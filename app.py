import streamlit as st
import sqlite3
import hashlib
import os
from datetime import datetime
from tinydb import TinyDB, Query
from transformers import pipeline
from pypdf import PdfReader
import fitz  # PyMuPDF
from PIL import Image
import io
import re

# ---------------- CONFIG ----------------
st.set_page_config("AI PDF Vault", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

DOC_DB = f"{DATA_DIR}/documents.db"
USER_DB = TinyDB(f"{DATA_DIR}/users.json")

# ---------------- DATABASE ----------------
conn = sqlite3.connect(DOC_DB, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT,
    filename TEXT,
    filehash TEXT UNIQUE,
    summary TEXT,
    content TEXT,
    created_at TEXT
)
""")
conn.commit()

# ---------------- AI MODEL ----------------
@st.cache_resource
def load_model():
    return pipeline(
        "summarization",
        model="facebook/bart-large-cnn",
        device=-1
    )

summarizer = load_model()

def chunk_text(text, max_chars=2000):
    return [text[i:i+max_chars] for i in range(0, len(text), max_chars)]

def ai_summary(text):
    chunks = chunk_text(text)
    summaries = []
    for c in chunks[:5]:
        out = summarizer(
            c,
            max_length=180,
            min_length=60,
            do_sample=False
        )[0]["summary_text"]
        summaries.append(out)
    return " ".join(summaries)

# ---------------- HELPERS ----------------
def file_hash(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()

def extract_text(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join([p.extract_text() or "" for p in reader.pages])

def render_pdf_thumbnail(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    return Image.open(io.BytesIO(pix.tobytes()))

def highlight(text, query):
    if not query:
        return text
    return re.sub(
        f"({re.escape(query)})",
        r"<mark>\1</mark>",
        text,
        flags=re.IGNORECASE
    )

# ---------------- AUTH ----------------
def login():
    st.subheader("🔐 Login / Signup")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        q = Query()
        user = USER_DB.get((q.username == username) & (q.password == hashlib.sha256(password.encode()).hexdigest()))
        if user:
            st.session_state.user = username
            st.success("Logged in")
            st.rerun()
        else:
            st.error("Invalid credentials")

    if st.button("Signup"):
        q = Query()
        if USER_DB.get(q.username == username):
            st.warning("User exists")
        else:
            USER_DB.insert({
                "username": username,
                "password": hashlib.sha256(password.encode()).hexdigest()
            })
            st.success("Account created")

# ---------------- MAIN ----------------
if "user" not in st.session_state:
    login()
    st.stop()

st.sidebar.success(f"👤 {st.session_state.user}")
if st.sidebar.button("Logout"):
    del st.session_state.user
    st.rerun()

st.title("📚 AI PDF Summary Vault")

# ---------------- UPLOAD ----------------
uploaded = st.file_uploader(
    "Upload PDFs",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded:
    for pdf in uploaded:
        pdf_bytes = pdf.read()
        h = file_hash(pdf_bytes)

        cur.execute("SELECT 1 FROM documents WHERE filehash=?", (h,))
        if cur.fetchone():
            st.warning(f"{pdf.name} already exists")
            continue

        text = extract_text(pdf_bytes)
        with st.spinner(f"Summarizing {pdf.name}"):
            summary = ai_summary(text)

        cur.execute("""
        INSERT INTO documents
        (user, filename, filehash, summary, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            st.session_state.user,
            pdf.name,
            h,
            summary,
            text,
            datetime.now().isoformat()
        ))
        conn.commit()

        st.success(f"{pdf.name} processed")

# ---------------- SEARCH ----------------
search = st.text_input("🔍 Search summaries")

cur.execute("""
SELECT id, filename, summary, created_at, content
FROM documents
WHERE user=?
ORDER BY created_at DESC
""", (st.session_state.user,))

docs = cur.fetchall()

# ---------------- DISPLAY ----------------
for i, (doc_id, name, summary, created, content) in enumerate(docs):
    if search and search.lower() not in summary.lower():
        continue

    with st.expander(f"📄 {name} — {created[:10]}"):
        st.markdown(highlight(summary, search), unsafe_allow_html=True)

        st.download_button(
            "⬇️ Download Summary",
            summary,
            file_name=f"{name}_summary.txt",
            key=f"dl_{doc_id}"
        )

# ---------------- ANALYTICS ----------------
st.sidebar.markdown("## 📊 Analytics")
st.sidebar.metric("Total PDFs", len(docs))
st.sidebar.metric("Total Words", sum(len(d[4].split()) for d in docs))
st.sidebar.metric("Total Summaries", len(docs))