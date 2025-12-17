"""
Test de sintaxis para todos los módulos del proyecto.

Valida que no hay errores de sintaxis Python antes de ejecutar migraciones.
Útil para detectar errores introducidos durante refactoring.
"""

import py_compile
import os
import sys

# Agregar directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def test_syntax():
    """
    Compila todos los .py del proyecto sin ejecutarlos.

    Retorna:
        tuple: (success: bool, errors: list)
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    errors = []

    # Archivos core (siempre validar)
    core_files = [
        "mongomigra.py",
        "config.py",
        "dbsetup.py",
        "migrators/base.py",
    ]

    # Archivos de migradores (dinámico basado en config.MIGRATION_ORDER)
    migrator_files = []
    for collection_name in config.MIGRATION_ORDER:
        cfg = config.get_collection_config(collection_name)
        schema = cfg["postgres_schema"]
        migrator_file = f"migrators/{schema}.py"
        migrator_files.append(migrator_file)

    # Combinar todos los archivos a validar
    files_to_check = core_files + migrator_files

    print("🔍 Validando sintaxis de archivos Python...")
    print(f"   Total archivos: {len(files_to_check)}")

    for filepath in files_to_check:
        full_path = os.path.join(project_root, filepath)

        if not os.path.exists(full_path):
            errors.append(f"Archivo no encontrado: {filepath}")
            print(f"   ❌ {filepath} (no existe)")
            continue

        try:
            py_compile.compile(full_path, doraise=True)
            print(f"   ✅ {filepath}")
        except py_compile.PyCompileError as e:
            errors.append(f"{filepath}: {e}")
            print(f"   ❌ {filepath}: {e}")

    return len(errors) == 0, errors


if __name__ == "__main__":
    success, errors = test_syntax()

    print("\n" + "=" * 70)

    if success:
        print("✅ Todos los archivos tienen sintaxis correcta")
        print("=" * 70)
        sys.exit(0)
    else:
        print(f"❌ Errores encontrados: {len(errors)}")
        print("=" * 70)
        for error in errors:
            print(f"   - {error}")
        sys.exit(1)
