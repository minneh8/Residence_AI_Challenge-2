import os
from dotenv import load_dotenv
from canvasapi import Canvas

# Carrega as variáveis de ambiente do .env
load_dotenv()

API_URL = os.getenv("CANVAS_API_URL")
API_KEY = os.getenv("CANVAS_API_KEY")

# Inicializa o Canvas
canvas = Canvas(API_URL, API_KEY)

# Teste simples: pega os dados do próprio usuário
user = canvas.get_current_user()
print(f"✅ Conectado com sucesso como: {user.name}")

# Listar os cursos ativos
print("\nDisciplinas ativas:")
courses = user.get_courses(enrollment_state="active")
for course in courses:
    if hasattr(course, "name"):
        print(f"- [{course.id}] {course.name}")