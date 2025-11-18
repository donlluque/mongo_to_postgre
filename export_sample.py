"""
export_sample.py - Exporta muestra de colección MongoDB a JSON

Uso:
    python export_sample.py <collection_name> [limit]
    
Ejemplo:
    python export_sample.py lml_listbuilder_mesa4core 200
"""

import sys
import json
import os
from pathlib import Path
from bson.json_util import dumps
from pymongo import MongoClient
import config


def export_collection_sample(collection_name, limit=200):
    """
    Exporta muestra de una colección a JSON en formato Extended JSON.
    
    Args:
        collection_name: Nombre de la colección en MongoDB
        limit: Número de documentos a exportar
    """
    client = MongoClient(config.MONGO_URI)
    db = client[config.MONGO_DATABASE_NAME]
    collection = db[collection_name]
    
    # Obtener documentos
    print(f"📥 Obteniendo {limit} documentos de '{collection_name}'...")
    docs = list(collection.find().limit(limit))
    
    if not docs:
        print(f"⚠️  La colección '{collection_name}' está vacía o no existe")
        return
    
    # Crear directorio samples/ si no existe
    samples_dir = Path("samples")
    samples_dir.mkdir(exist_ok=True)
    
    # Serializar usando bson.json_util (mantiene tipos de MongoDB)
    json_output = dumps(docs, indent=2, ensure_ascii=False)
    
    # Guardar archivo en samples/
    filename = samples_dir / f"{collection_name}_sample.json"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(json_output)
    
    print(f"✅ Exportados {len(docs)} documentos")
    print(f"📄 Archivo: {filename}")
    print(f"📊 Tamaño: {len(json_output) / 1024:.2f} KB")


if __name__ == "__main__":
    # Argumentos por línea de comandos
    if len(sys.argv) < 2:
        print("Uso: python export_sample.py <collection_name> [limit]")
        print("Ejemplo: python export_sample.py lml_listbuilder_mesa4core 200")
        sys.exit(1)
    
    collection_name = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    
    export_collection_sample(collection_name, limit)