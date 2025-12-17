# mongo_to_postgre

Proyecto para realizar la migracion de una bbdd mongodb a postgre convirtiendola en relacional

# Estructura del proyecto

```

mongo_to_postgre/
├── config.py                          # Ya existe, lo extendemos
├── db_setup.py                        # Setup inicial (una sola vez)
├── mongomigra.py                      # Solo migra datos
├── export_sample.py                   # Genera una exportación de 200 documentos en json para analizar la estructura
├── analyze_*.py                       # Crea txt con el análisis del sample de 200 documentos
└── migrators/                         # Lógica específica por colección
|    ├── lml_processes.py              # Logica de extraccion para esta coleccion especifica
|    └── lml_listbuilder.py            # Igual que la anterior, cada coleccion = 1 archivo
└── samples/                           # Samples y resultados de analisis
     ├── lml_*_mesa4core_sample.json   # Sample con 200 documentos de la coleccion para analizar
     └── lml_*_analysis.txt            # Resultado del análisis al correr analyze_*.py sobre el json de sample

```

# Flujo de Trabajo

Este documento detalla el proceso estandarizado para migrar colecciones, asegurando integridad referencial y rendimiento.

### 1. Fase de Descubrimiento (Sampling & Analysis)

No se puede migrar lo que no se conoce.

- **Sample JSON:** Tomamos 200 documentos representativos. Un solo documento no sirve porque no muestra la variabilidad de los datos (campos opcionales, arrays vacíos vs llenos).
- **Script de Análisis (`analyze_*.py`):**
  - **Objetivo:** Determinar la cardinalidad de los arrays (¿son listas simples o requieren tablas hijas?), detectar tipos de datos mixtos y encontrar claves foráneas (FKs) ocultas.
  - **Resultado Crítico:** El archivo `.txt`. Este es el "plano" sobre el cual tomamos decisiones de arquitectura (ej: "esto va como `JSONB`", "esto requiere una tabla `_fields`").

### 2. Fase de Definición (Blueprint)

Antes de tocar la lógica de migración, preparamos el terreno.

- **`config.py`:** Es el registro civil del sistema.
  - Define **quién** es la colección (nombre).
  - Define **qué** es (Fuente de Verdad o Consumidor).
  - Define **cuándo** corre (Orden de migración y dependencias). _Sin esto, el orquestador ignora tu código._
- **`dbsetup.py`:** Es la estructura física.
  - Traduce el análisis del paso 1 a SQL.
  - Aquí se define la integridad referencial (_Foreign Keys_). Si definimos una FK estricta aquí, el código Python **debe** manejar la lógica de "Ghost Users" o fallará.

### 3. Fase de Implementación (El Migrador)

Es el archivo `migrators/lml_*.py`. Aquí ocurre la magia del **ETL** (_Extract, Transform, Load_).

- **Class Naming:** Debe coincidir con la convención del orquestador (`LmlNombreMigrator`) para que la carga dinámica funcione.
- **Extracción (`extract_data`):** Convierte el diccionario anidado de Mongo en una estructura plana (tuplas) para SQL.
- **Transformación:** Manejo de fechas (`$date`), booleanos y serialización de objetos complejos a strings JSON (`json.dumps`).
- **Manejo de Integridad:**
  - **Ghost Users:** Si el `dbsetup.py` exige un usuario existente, el migrador debe verificar si existe y crearlo si falta.
  - **Filtering:** Si una sub-tabla (ej: `starting_privileges`) apunta a catálogos inexistentes, se filtran para evitar errores de FK.

### 4. Fase de Ejecución (Orquestación)

**`mongomigra.py`:** No contiene lógica de negocio específica. Su trabajo es:

1.  Leer `config.py` para saber el orden.
2.  Instanciar la clase del migrador dinámicamente.
3.  Gestionar la conexión a Mongo y Postgres.
4.  Ejecutar el bucle de lotes (_batching_) para no saturar la memoria.

> **Conclusión Crítica:** El error más común es saltarse la **Fase 2**. Si intentas escribir el migrador sin haber definido bien el `dbsetup.py` (tablas) y el `config.py` (dependencias), terminarás refactorizando código constantemente porque la base de datos rechazará tus datos. **El esquema manda sobre el código.**
