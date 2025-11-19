"""
Runner principal de tests.

Ejecuta todos los tests en orden lógico y reporta resultados consolidados.
"""

import sys
import os

# Agregar tests al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tests'))

from test_syntax import test_syntax
from test_migrator_interface import run_all_tests as test_interface
from test_schema_integrity import run_all_tests as test_schema


def main():
    """
    Ejecuta suite completa de tests.
    
    Orden de ejecución:
    1. Sintaxis (si falla aquí, no tiene sentido continuar)
    2. Interfaz (validar herencia y métodos)
    3. Schema (validar coherencia entre código y base de datos)
    """
    print("=" * 70)
    print("🚀 INICIANDO SUITE DE TESTS")
    print("=" * 70)
    
    results = {}
    
    # Test 1: Sintaxis
    print("\n" + "=" * 70)
    print("📝 FASE 1: VALIDACIÓN DE SINTAXIS")
    print("=" * 70)
    success, errors = test_syntax()
    results['syntax'] = success
    
    if not success:
        print("\n⚠️  Errores de sintaxis detectados. Corregir antes de continuar.")
        print_summary(results)
        return False
    
    # Test 2: Interfaz
    print("\n" + "=" * 70)
    print("🔌 FASE 2: VALIDACIÓN DE INTERFAZ")
    print("=" * 70)
    results['interface'] = test_interface()
    
    # Test 3: Schema
    print("\n" + "=" * 70)
    print("🗄️  FASE 3: VALIDACIÓN DE SCHEMAS")
    print("=" * 70)
    results['schema'] = test_schema()
    
    # Resumen final
    print_summary(results)
    
    return all(results.values())


def print_summary(results):
    """Imprime resumen de resultados de tests."""
    print("\n" + "=" * 70)
    print("📊 RESUMEN DE TESTS")
    print("=" * 70)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {status}  {test_name.capitalize()}")
    
    print("=" * 70)
    
    if all(results.values()):
        print("✅ TODOS LOS TESTS PASARON - Sistema listo para migración")
    else:
        print("❌ HAY TESTS FALLANDO - Corregir antes de migrar")
    
    print("=" * 70)


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)