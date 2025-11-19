"""
Test de sintaxis para todos los módulos del proyecto.

Valida que no hay errores de sintaxis Python antes de ejecutar migraciones.
Útil para detectar errores introducidos durante refactoring.
"""

import py_compile
import os
import sys


def test_syntax():
    """
    Compila todos los .py del proyecto sin ejecutarlos.
    
    Retorna:
        tuple: (success: bool, errors: list)
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    errors = []
    
    # Archivos a validar
    files_to_check = [
        'mongomigra.py',
        'config.py',
        'dbsetup.py',
        'migrators/base.py',
        'migrators/lml_processes.py',
        'migrators/lml_listbuilder.py',
    ]
    
    print("🔍 Validando sintaxis de archivos Python...")
    
    for filepath in files_to_check:
        full_path = os.path.join(project_root, filepath)
        
        if not os.path.exists(full_path):
            errors.append(f"Archivo no encontrado: {filepath}")
            continue
        
        try:
            py_compile.compile(full_path, doraise=True)
            print(f"   ✅ {filepath}")
        except py_compile.PyCompileError as e:
            errors.append(f"{filepath}: {e}")
            print(f"   ❌ {filepath}: {e}")
    
    return len(errors) == 0, errors


if __name__ == '__main__':
    success, errors = test_syntax()
    
    if success:
        print("\n✅ Todos los archivos tienen sintaxis correcta")
        sys.exit(0)
    else:
        print(f"\n❌ Errores encontrados: {len(errors)}")
        for error in errors:
            print(f"   - {error}")
        sys.exit(1)