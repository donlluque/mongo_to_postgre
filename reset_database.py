# reset_database.py
"""
Script para limpiar completamente la base de datos PostgreSQL antes de migración.

ADVERTENCIA: Esto destruye TODOS los datos. Solo usar en sincronización nocturna.
"""

import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()


def reset_database():
    """Elimina todos los schemas de migración y los recrea vacíos."""

    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )

    cursor = conn.cursor()

    print("=" * 70)
    print("🗑️  LIMPIEZA COMPLETA DE BASE DE DATOS")
    print("=" * 70)

    # Lista de schemas a eliminar (todos los lml_*)
    schemas_to_drop = [
        "lml_users",
        "lml_usersgroups",
        "lml_processes",
        "lml_listbuilder",
        "lml_formbuilder",
        "lml_processtypes",
        "lml_people",
        # Agregar aquí los schemas futuros
    ]

    for schema in schemas_to_drop:
        try:
            print(f"\n🗑️  Eliminando schema '{schema}'...")
            cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            print(f"   ✅ Schema '{schema}' eliminado")
        except Exception as e:
            print(f"   ⚠️  Error eliminando '{schema}': {e}")

    conn.commit()
    cursor.close()
    conn.close()

    print("\n" + "=" * 70)
    print("✅ LIMPIEZA COMPLETA FINALIZADA")
    print("=" * 70)
    print("\nAhora ejecutar:")
    print("  1. python dbsetup.py    (recrear estructura)")
    print("  2. python mongomigra.py (migrar datos)")


if __name__ == "__main__":
    import sys

    # Seguridad: pedir confirmación
    print("\n⚠️  ADVERTENCIA: Esto eliminará TODOS los datos migrados.")
    response = input("¿Continuar? (escribir 'SI' en mayúsculas): ")

    if response == "SI":
        reset_database()
    else:
        print("\n❌ Operación cancelada")
        sys.exit(0)
