import streamlit as st
import pandas as pd
import os
import json
import glob
import re
from google import genai

st.set_page_config(page_title="EduProf Pro", layout="wide")
st.title("🎓 EduProf: Sistema de Gestión Académica")

if not os.path.exists("uploads"): os.makedirs("uploads")

# --- CONFIGURACIÓN DE LA IA ---
# Nota: Puedes configurar tu API Key como un secreto en Streamlit Cloud (st.secrets["GEMINI_API_KEY"]) 
# o ingresarla directamente para pruebas locales.
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=API_KEY)

# --- LÓGICA DE ARCHIVOS ---
def cargar_estado(file):
    if os.path.exists(file):
        with open(file, "r") as f: 
            data = json.load(f)
            if "datos" not in data: data["datos"] = {}
            if "preguntas" not in data: data["preguntas"] = []
            return data
    return {"publicado": False, "datos": {"uni": "UAP", "titulo": "", "limite_envios": 1}, "preguntas": []}

def guardar_estado(file, estado):
    with open(file, "w") as f: json.dump(estado, f)

def calificar_imagen_con_ia(img_path, nombre_img, estado, client):
    """Envía una imagen a la IA junto con la pregunta y criterio reales, y devuelve la nota (float) ya acotada al puntaje máximo."""
    match_p = re.search(r"_P(\d+)_Imagen", nombre_img)
    idx_pregunta = int(match_p.group(1)) - 1 if match_p else None

    if idx_pregunta is not None and 0 <= idx_pregunta < len(estado["preguntas"]):
        pregunta_actual = estado["preguntas"][idx_pregunta]
        enunciado_actual = pregunta_actual.get("q", "")
        criterio_actual = pregunta_actual.get("a", "")
        puntaje_max = pregunta_actual.get("p", 5)
    else:
        enunciado_actual = "(No se pudo identificar la pregunta)"
        criterio_actual = "(Sin criterio definido)"
        puntaje_max = 5

    uploaded_file = client.files.upload(file=img_path)
    prompt_ia = (
        "Eres un profesor experto evaluando exámenes. "
        f"La pregunta del examen es: \"{enunciado_actual}\". "
        f"El criterio de evaluación / respuesta esperada es: \"{criterio_actual}\". "
        f"El puntaje máximo de esta pregunta es {puntaje_max}. "
        "Analiza la imagen adjunta, que debería contener la respuesta del alumno a esa pregunta. "
        "Si la imagen NO corresponde a una respuesta de examen (por ejemplo, es una foto personal, "
        "un documento en blanco, o contenido sin relación con la pregunta), devuelve el número 0. "
        "Si sí corresponde, evalúa qué tan correcto y completo es el desarrollo comparado con el criterio, "
        "y devuelve un número entero o decimal entre 0 y el puntaje máximo. "
        "Devuelve ÚNICAMENTE el número, sin texto adicional."
    )
    response = client.models.generate_content(
        model='gemini-3.5-flash',
        contents=[uploaded_file, prompt_ia]
    )
    texto_respuesta = response.text.strip()
    nota = float(''.join(c for c in texto_respuesta if c.isdigit() or c == '.'))
    nota = max(0.0, min(nota, float(puntaje_max)))
    return nota

# --- PANEL LATERAL ---
password = st.sidebar.text_input("Clave de Admin", type="password")
es_admin = (password == st.secrets.get("ADMIN_PASSWORD", ""))

if es_admin:
    st.sidebar.success("Modo Administrador Activo")

    # --- PANEL LATERAL: SELECTOR DE EVALUACIÓN ---
    with st.sidebar.expander("Ver exámenes por institución"):
        archivos = [f for f in os.listdir('.') if f.startswith("estado_")]
        for f in archivos:
            try:
                with open(f, "r") as file: d = json.load(file)
                uni = d.get("datos", {}).get("uni", "Sin definir")
                cod = f.replace("estado_", "").replace(".json", "")
                
                col1, col2 = st.columns([4, 1])
                if col1.button(f"{uni}: {cod}", key=f"sel_{cod}"):
                    st.session_state.codigo_seleccionado = cod
                    st.rerun()
                if col2.button("🗑️", key=f"del_{cod}"):
                    if os.path.exists(f): os.remove(f)
                    if os.path.exists(f"entregas_{cod}.csv"): os.remove(f"entregas_{cod}.csv")
                    st.rerun()
            except: continue

if es_admin:
    if 'codigo_seleccionado' in st.session_state:
        codigo_curso = st.sidebar.text_input("Código del Examen", value=st.session_state.codigo_seleccionado)
    else:
        codigo_curso = st.sidebar.text_input("Código del Examen")
else:
    codigo_curso = st.sidebar.text_input("Ingresa el Código de tu Examen")

if not codigo_curso: st.stop()

ESTADO_FILE = f"estado_{codigo_curso}.json"
ENTREGAS_FILE = f"entregas_{codigo_curso}.csv"
estado = cargar_estado(ESTADO_FILE)

# --- PANEL DE ADMINISTRACIÓN ---
if es_admin:
    tab1, tab2 = st.tabs(["Creación", "Calificar Entregas"])
    
    with tab1: 
        if 'edit_index' not in st.session_state: st.session_state.edit_index = None
        idx = st.session_state.edit_index
        p_data = estado["preguntas"][idx] if idx is not None else {}
        
        uni = st.selectbox("Universidad", ["UAP", "Cibertec", "UPN", "Certus"])
        titulo = st.text_input("Título", estado["datos"].get("titulo", ""))
        tipo = st.selectbox("Tipo", ["Numérica", "Opción Múltiple", "Imagen/Abierta"], 
                            index=["Numérica", "Opción Múltiple", "Imagen/Abierta"].index(p_data.get("tipo", "Numérica")))
        enunciado = st.text_area("Enunciado", value=p_data.get("q", ""))
        opciones = st.text_area("Opciones (separadas por coma)", value=p_data.get("opciones", "")) if tipo == "Opción Múltiple" else ""
        puntaje = st.number_input("Puntaje máximo de la pregunta", value=p_data.get("p", 5))
        correcta = st.text_input("Respuesta correcta / Criterio de evaluación", value=p_data.get("a", ""))
        limite_envios = st.number_input("Límite de envíos permitidos", min_value=1, value=estado["datos"].get("limite_envios", 1))

        if st.button("Guardar Pregunta" if idx is not None else "Agregar pregunta"):
            data = {"tipo": tipo, "q": enunciado, "a": correcta, "p": puntaje, "opciones": opciones}
            if idx is not None: estado["preguntas"][idx] = data
            else: estado["preguntas"].append(data)
            guardar_estado(ESTADO_FILE, estado); st.rerun()

        for i, p in enumerate(estado["preguntas"]):
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"P{i+1}: {p['q'][:15]}...")
            if c2.button("✏️", key=f"e{i}"): st.session_state.edit_index = i; st.rerun()
            if c3.button("🗑️", key=f"d{i}"): estado["preguntas"].pop(i); guardar_estado(ESTADO_FILE, estado); st.rerun()

        if st.button("Publicar Examen"):
            estado.update({"publicado": True, "datos": {"uni": uni, "titulo": titulo, "limite_envios": limite_envios}})
            guardar_estado(ESTADO_FILE, estado)
            st.session_state.mensaje_exito = "¡Examen publicado con éxito!"
            if 'codigo_seleccionado' in st.session_state: del st.session_state['codigo_seleccionado']
            if 'edit_index' in st.session_state: st.session_state.edit_index = None
            st.rerun()

        if 'mensaje_exito' in st.session_state:
            st.success(st.session_state.mensaje_exito)
            del st.session_state.mensaje_exito

    with tab2: 
        st.subheader("Calificar Entregas (Manual y con IA)")
        if os.path.exists(ENTREGAS_FILE):
            df = pd.read_csv(ENTREGAS_FILE)
            for col_nota in ['Nota_Auto', 'Nota_Manual', 'Nota']:
                if col_nota in df.columns:
                    df[col_nota] = df[col_nota].astype(float)
            
            st.write("Selecciona un envío para borrar:")
            for i, row in df.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"Alumno: **{row['Alumno']}** | Nota Total: {row['Nota']}")
                if c2.button("🗑️", key=f"del_envio_{i}"):
                    df = df.drop(i) 
                    df.to_csv(ENTREGAS_FILE, index=False)
                    st.rerun()
            
            st.divider()

            if st.button("⚡ Calificar y guardar notas de TODOS los alumnos con IA", key="btn_ia_todos_alumnos"):
                alumnos_lista = df['Alumno'].unique()
                total = len(alumnos_lista)
                progreso = st.progress(0, text="Iniciando calificación masiva...")
                errores_globales = []

                for n, alumno in enumerate(alumnos_lista):
                    progreso.progress(n / total, text=f"Calificando a {alumno} ({n+1}/{total})...")
                    imagenes_este_alumno = glob.glob(f"uploads/{codigo_curso}_{alumno}_P*_Imagen.png")
                    suma_notas = 0.0

                    for img_path in imagenes_este_alumno:
                        nombre_img = os.path.basename(img_path)
                        try:
                            nota_ia = calificar_imagen_con_ia(img_path, nombre_img, estado, client)
                            st.session_state[img_path] = nota_ia
                            suma_notas += nota_ia
                        except Exception as e:
                            errores_globales.append(f"{alumno} - {nombre_img}: {e}")

                    df.loc[df['Alumno'] == alumno, 'Nota_Manual'] = suma_notas
                    df.loc[df['Alumno'] == alumno, 'Nota'] = df['Nota_Auto'] + df['Nota_Manual']

                progreso.progress(1.0, text="¡Listo!")
                df.to_csv(ENTREGAS_FILE, index=False)

                if errores_globales:
                    st.error("Hubo errores calificando algunas imágenes:\n" + "\n".join(errores_globales))
                st.success(f"Se calificaron y guardaron las notas de {total} alumno(s) con éxito.")
                st.rerun()

            st.divider()
            
            sel_alumno = st.selectbox("Seleccionar Alumno", df['Alumno'].unique())
            imagenes_alumno = glob.glob(f"uploads/{codigo_curso}_{sel_alumno}_P*_Imagen.png")
            notas_por_pregunta = {}
            
            if imagenes_alumno:
                if st.button("🤖 Calificar TODAS las preguntas con IA", key=f"btn_ia_todas_{sel_alumno}"):
                    with st.spinner("La IA está calificando todas las respuestas de este alumno..."):
                        errores = []
                        for img_path in imagenes_alumno:
                            nombre_img = os.path.basename(img_path)
                            try:
                                nota_ia = calificar_imagen_con_ia(img_path, nombre_img, estado, client)
                                st.session_state[img_path] = nota_ia
                            except Exception as e:
                                errores.append(f"{nombre_img}: {e}")
                        if errores:
                            st.error("Hubo errores calificando algunas imágenes:\n" + "\n".join(errores))
                    st.rerun()

                for img_path in imagenes_alumno:
                    st.image(img_path)
                    nombre_img = os.path.basename(img_path)
                    
                    col_num, col_ia, col_del = st.columns([2, 1, 1])
                    with col_num:
                        nota_ingresada = st.number_input(
                            f"Nota para {nombre_img}:", min_value=0.0, max_value=20.0, step=0.5, key=img_path
                        )
                        notas_por_pregunta[img_path] = nota_ingresada
                        
                    with col_del:
                        if st.button("🗑️ Borrar", key=f"del_img_{img_path}"):
                            os.remove(img_path)
                            st.success(f"Imagen {nombre_img} eliminada")
                            st.rerun()
                        
                    with col_ia:
                        if st.button(f"🤖 Calificar con IA", key=f"btn_ia_{img_path}"):
                            with st.spinner("La IA está analizando la imagen..."):
                                try:
                                    nota_ia = calificar_imagen_con_ia(img_path, nombre_img, estado, client)
                                    st.session_state[img_path] = nota_ia
                                except Exception as e:
                                    st.error(f"Error al calificar con IA: {e}")
                            st.rerun()
                
                if st.button("Guardar Notas"):
                    df.loc[df['Alumno'] == sel_alumno, 'Nota_Manual'] = sum(notas_por_pregunta.values())
                    df.loc[df['Alumno'] == sel_alumno, 'Nota'] = df['Nota_Auto'] + df['Nota_Manual']
                    df.to_csv(ENTREGAS_FILE, index=False)
                    st.success("Nota total actualizada con éxito"); st.rerun()
            else:
                st.warning("No se encontraron imágenes para este alumno en este examen.")
            
            st.divider()
            st.dataframe(df)

# --- MODO ALUMNO ---
else:
    if estado.get("publicado"):
        if 'enviado' not in st.session_state: st.session_state.enviado = False
        if not st.session_state.enviado:
            st.subheader(f"🏛️ {estado['datos'].get('uni')} - {estado['datos'].get('titulo')}")
            nombre = st.text_input("Nombre completo")
            respuestas = {}
            for i, p in enumerate(estado["preguntas"]):
                st.write(f"**P{i+1} ({p['p']} pts):** {p['q']}")
                if p["tipo"] == "Opción Múltiple":
                    respuestas[i] = st.radio(f"Opción para P{i+1}", p["opciones"].split(","), key=f"r_{i}")
                elif p["tipo"] == "Imagen/Abierta":
                    archivo = st.file_uploader(f"Cargar respuesta P{i+1}", type=["png", "jpg"], key=f"img_{i}")
                    if archivo:
                        nombre_archivo_normalizado = nombre.strip().upper()
                        with open(f"uploads/{codigo_curso}_{nombre_archivo_normalizado}_P{i+1}_Imagen.png", "wb") as f: f.write(archivo.getbuffer())
                    respuestas[i] = "Imagen"
                else:
                    respuestas[i] = st.text_input(f"Respuesta P{i+1}", key=f"t_{i}")

            if st.button("Enviar"):
                if not nombre or nombre.strip() == "":
                    st.error("⚠️ El campo 'Nombre completo' es obligatorio.")
                else:
                    nombre_normalizado = nombre.strip().upper()
                    ya_envio = False
        
                    if os.path.exists(ENTREGAS_FILE):
                        df_historial = pd.read_csv(ENTREGAS_FILE)
                        if nombre_normalizado in df_historial['Alumno'].str.strip().str.upper().values:
                            ya_envio = True
        
                    if ya_envio:
                        st.error(f"❌ {nombre}, ya has enviado este examen. Solo se permite un envío.")
                    else:
                        nota_auto = sum(p['p'] for i, p in enumerate(estado["preguntas"]) if str(respuestas.get(i)) == str(p['a']))
            
                        nueva_entrega = pd.DataFrame([{
                            'Alumno': nombre_normalizado, 
                            'Nota_Auto': nota_auto, 
                            'Nota_Manual': 0, 
                            'Nota': nota_auto 
                        }])
                        nueva_entrega.to_csv(ENTREGAS_FILE, mode='a', index=False, header=not os.path.exists(ENTREGAS_FILE))
            
                        st.session_state.enviado = True
                        st.rerun()
        else:
            st.success("Enviado con éxito"); 
            if st.button("Hacer otro"): st.session_state.enviado = False; st.rerun()
