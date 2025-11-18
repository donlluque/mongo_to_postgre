# Proyecto de Migración MongoDB a PostgreSQL - Contexto Completo

## 📋 Visión General del Proyecto

### Propósito y Visión
Este proyecto implementa un sistema completo de migración desde una base de datos MongoDB (`mesa4core`) hacia una base de datos PostgreSQL relacional (`mesamongo`). El objetivo no es simplemente transferir datos, sino **transformarlos** de un modelo de documentos NoSQL con estructuras anidadas a un modelo relacional propiamente normalizado siguiendo las mejores prácticas de diseño de bases de datos.

### ¿Por qué esta migración?
La decisión de migrar desde MongoDB hacia PostgreSQL responde a varias necesidades:

1. **Integridad de Datos**: Implementar integridad referencial mediante claves foráneas y restricciones
2. **Normalización**: Eliminar la duplicación de datos inherente al modelo desnormalizado de MongoDB
3. **Consultas Complejas**: Habilitar JOINs eficientes y consultas relacionales complejas
4. **Estandarización**: Consolidar entidades compartidas (usuarios, áreas, clientes) en tablas de única fuente de verdad

## 🏗️ Arquitectura Técnica

### Diseño de Esquemas Híbrido
La arquitectura implementa un **patrón de esquemas híbridos** en PostgreSQL:

#### Schema Public (Entidades Compartidas)
Aloja entidades que se reutilizan a través de múltiples colecciones:
- `public.users` - Usuarios del sistema
- `public.areas` - Áreas organizacionales
- `public.subareas` - Subdivisiones de áreas
- `public.roles` - Roles de usuario
- `public.groups` - Grupos de usuarios
- `public.user_groups` - Tabla de relación muchos-a-muchos
- `public.customers` - Clientes (añadida recientemente)

#### Schemas Específicos por Colección
Cada colección de MongoDB obtiene su propio schema para datos específicos:
- Schema `lml_processes` contiene:
  - `main` - Registros principales de procesos
  - `movements` - Historial de movimientos de procesos
  - `last_movements` - Último movimiento por proceso
  - `initiator_fields` - Campos dinámicos del iniciador del proceso
  - `process_documents` - Documentos asociados

### ¿Por qué Híbrido vs. Schema Único?
Esta arquitectura proporciona:
- **Organización**: Separación clara entre datos compartidos y específicos de colección
- **Escalabilidad**: Nuevas colecciones pueden agregarse sin colisiones de nombres
- **Mantenibilidad**: Fácil de entender la propiedad de los datos
- **Flexibilidad**: Futuras colecciones pueden reutilizar entidades públicas o crear nuevas

## 🔧 Stack Tecnológico

### Tecnologías Core
- **Python 3.12**: Lenguaje de programación principal
- **pymongo**: Driver y cliente de MongoDB
- **psycopg2**: Adaptador de PostgreSQL
- **python-dotenv**: Gestión de variables de entorno

### Sistemas de Base de Datos
- **MongoDB** (Origen): Base de datos NoSQL orientada a documentos
- **PostgreSQL** (Destino): Base de datos SQL relacional

## 📊 Transformación del Modelo de Datos

### Estructura MongoDB (Original)
Los documentos en la colección `lml_processes_mesa4core` contienen objetos profundamente anidados:

```javascript
{
  _id: ObjectId("..."),
  processNumber: "12345",
  customerId: "CUST001",
  createdBy: {
    user: {
      id: "USR001",
      email: "usuario@ejemplo.com",
      firstname: "Juan",
      lastname: "Pérez",
      area: { id: "AREA01", name: "Operaciones" },
      subarea: { id: "SUB01", name: "Logística" },
      role: { id: "ROLE01", name: "Gerente" },
      groups: [{ id: "GRP01", name: "Administradores" }]
    }
  },
  movements: [
    { at: ISODate("..."), id: "MOV001", to: "destino" }
  ],
  initiatorFields: {
    campo1: { id: "FLD01", name: "Campo Uno" }
  }
}
```

### Estructura PostgreSQL (Transformada)

#### Entidades Compartidas (schema public)
```sql
public.users (
  id VARCHAR(255) PRIMARY KEY,
  email VARCHAR(255) UNIQUE,
  firstname VARCHAR(255),
  lastname VARCHAR(255),
  area_id VARCHAR(255) → public.areas(id),
  subarea_id VARCHAR(255) → public.subareas(id),
  role_id VARCHAR(255) → public.roles(id)
)

public.customers (
  id VARCHAR(255) PRIMARY KEY
)
```

#### Específico de Colección (schema lml_processes)
```sql
lml_processes.main (
  process_id VARCHAR(255) PRIMARY KEY,  -- Anteriormente mongo_id
  process_number VARCHAR(255),
  customer_id VARCHAR(255) → public.customers(id),
  created_by_user_id VARCHAR(255) → public.users(id),
  updated_by_user_id VARCHAR(255) → public.users(id),
  ...
)

lml_processes.movements (
  id SERIAL PRIMARY KEY,
  process_id VARCHAR(255) → lml_processes.main(process_id),  -- Anteriormente record_id
  movement_at TIMESTAMP,
  destination_id VARCHAR(255),
  destination_type VARCHAR(50)
)
```

### Convenciones de Nomenclatura Clave
Las mejoras recientes establecen patrones claros:

1. **Claves Primarias**: Usar nombres semánticos (`process_id` no `mongo_id`)
2. **Claves Foráneas**: Coincidir con nombres de claves primarias referenciadas (`process_id` no `record_id`)
3. **Consistencia**: La misma entidad se referencia de la misma forma en todos lados

## 📜 Scripts Actuales

### `config.py` - Gestión de Configuración
Centraliza toda la configuración no sensible:

```python
# Detalles de conexión MongoDB
MONGO_URI  # Construido desde variables de entorno
MONGO_DATABASE_NAME = "mesa4core"
MONGO_SOURCE_COLLECTION = "lml_processes_mesa4core"

# Detalles de conexión PostgreSQL
POSTGRES_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB'),  # "mesamongo"
    # ... otros parámetros de conexión
}

# Mapeos de nombres de tablas
TABLE_NAMES = { ... }

# Configuración de migración
POC_SCHEMA_NAME = "lml_processes"
BATCH_SIZE = 500  # Registros por inserción en lote
```

**Decisión de Diseño**: Separar la configuración de la lógica permite:
- Ajustes fáciles sin cambios de código
- Futura conversión a archivos de configuración (JSON/YAML)
- Documentación clara de los parámetros del sistema

### `mongomigra.py` - Motor de Migración
El script principal de migración implementa:

#### 1. Gestión de Conexiones
```python
def connect_to_mongo()
def connect_to_postgres()
```
Establecen conexiones con manejo de errores apropiado y configuración de timeouts.

#### 2. Creación de Schema
```python
def create_postgres_tables(pg_cursor, pg_conn)
```
Crea la estructura completa del schema híbrido. Actualmente usa `DROP TABLE CASCADE` para migraciones de pizarra limpia.

**Importante**: Esto es aceptable para POC pero debe refactorizarse para producción (ver Mejoras Futuras).

#### 3. Procesamiento de Entidades con Caché
```python
def process_user_data(user_obj, pg_cursor, caches)
def process_customer_data(customer_id, pg_cursor, caches)
```

**El Patrón de Caché**: Optimización crítica de rendimiento
- **Problema**: Sin caché, cada documento procesa usuarios redundantemente
- **Solución**: `set()` en memoria rastrea entidades ya procesadas
- **Impacto**: Mejora de velocidad de ~5x (2,000 docs/min vs. 400 docs/min)

```python
caches = {
    'users': set(),
    'customers': set(),
    # ... otras entidades
}

# Ruta rápida: búsqueda O(1)
if user_id in caches['users']:
    return user_id  # Saltar operación de base de datos

# Ruta lenta: Insertar en base de datos
pg_cursor.execute("INSERT INTO public.users ...")
caches['users'].add(user_id)  # Recordar para la próxima vez
```

#### 4. Migración por Lotes
```python
def migrate_collection(mongo_db, pg_cursor, pg_conn)
```

**Estrategia de Procesamiento por Lotes**:
- Acumula registros en listas en memoria (ej., `main_batch`, `movements_batch`)
- Inserta en lotes de 500 usando `executemany()`
- Hace commit de cada lote a la base de datos

**¿Por qué por Lotes?**
- `INSERT` único: ~10-50ms por registro = 20 registros/segundo
- `INSERT` por lotes: ~100ms por 500 registros = 5,000 registros/segundo
- Overhead de red reducido en ~99%

```python
if count % BATCH_SIZE == 0:
    pg_cursor.executemany(sql, main_batch)  # Inserción masiva
    main_batch = []  # Limpiar para el siguiente lote
    pg_conn.commit()
```

## 🐛 Problemas Resueltos

### 1. Timeout de Red Durante Migraciones Largas
**Problema**: Timeout del cursor de MongoDB después de 30 minutos de inactividad

**Error**:
```
pymongo.errors.NetworkTimeout: 10.100.20.142:27017: timed out
```

**Solución**: Agregado `no_cursor_timeout=True` a la creación del cursor
```python
documents_to_migrate = source_collection.find(no_cursor_timeout=True)
```

**Nota**: Mejora pendiente es usar sesiones explícitas para control completo de timeout.

### 2. Sobrecarga de Salida en Consola
**Problema**: Cada documento procesado creaba una nueva línea, haciendo los logs ilegibles

**Solución**: Retorno de carro con flush para actualizaciones en una sola línea
```python
print(f"\r   -> Documentos procesados: {count}/{total_docs}", end="", flush=True)
```
- `\r` - Retorna el cursor al inicio de la línea
- `end=""` - Previene salto de línea
- `flush=True` - Fuerza salida inmediata (requerido para terminales bash)

### 3. Cuello de Botella de Rendimiento
**Problema**: Ejecución inicial procesaba solo 400 documentos/minuto

**Causa Raíz**: `process_user_data()` hacía 3-5 llamadas a la base de datos por documento, incluso para usuarios repetidos

**Solución**: Implementado caché en memoria (ver Patrón de Caché arriba)

**Resultado**: Rendimiento mejorado a 2,000 documentos/minuto

### 4. Riesgo de Duplicación de Datos
**Problema**: Re-ejecutar el script podría crear registros duplicados

**Solución**: Cláusula `ON CONFLICT DO NOTHING` en todas las inserciones
```python
INSERT INTO public.users (...) VALUES (...)
ON CONFLICT (id) DO NOTHING;
```
Esto hace el script **idempotente**: seguro para ejecutar múltiples veces.

## ✅ Estado Actual

### Qué Está Funcionando
- ✅ Migración completa de la colección `lml_processes_mesa4core` (123,084 documentos)
- ✅ Arquitectura de schema híbrido implementada
- ✅ Rendimiento optimizado con caché y procesamiento por lotes
- ✅ Relaciones de claves foráneas apropiadas establecidas
- ✅ Migración idempotente (segura para re-ejecutar)
- ✅ Convenciones de nomenclatura semántica (`process_id` vs `mongo_id`)

### Resultados Verificados
- Base de datos: `mesamongo` creada y poblada
- Schema: `public` contiene 7 tablas de entidades compartidas
- Schema: `lml_processes` contiene 5 tablas específicas de colección
- Integridad de datos: Todas las claves foráneas referencian apropiadamente las tablas padre

## 🔮 Próximos Pasos

### Inmediatos (Requeridos Antes de la Siguiente Colección)

1. **Separar Setup de Migración**
   ```
   Actual:     mongomigra.py (crea tablas + migra datos)
   Requerido:  setup_database.py (crea tablas UNA VEZ)
               mongomigra.py (solo migra datos)
   ```
   **Por qué**: `DROP TABLE CASCADE` destruye datos de colecciones previas

2. **Implementar Sistema de Reglas de Migración**
   Definir reglas específicas por colección en `config.py`:
   ```python
   COLLECTION_RULES = {
       "lml_processes_mesa4core": {
           "primary_key_name": "process_id",
           "target_schema": "lml_processes",
           "shared_entities": ["users", "customers"],
           # ...
       }
   }
   ```

3. **Manejar Timeouts de Sesión de MongoDB**
   Implementar gestión explícita de sesión para prevenir advertencia de timeout de 30 minutos:
   ```python
   with mongo_client.start_session() as session:
       documents_to_migrate = source_collection.find(
           no_cursor_timeout=True,
           session=session
       )
   ```

### Mejoras Futuras

1. **Soporte Multi-Colección**
   - Descubrimiento/listado de colecciones
   - Migración paralela de colecciones independientes
   - Seguimiento de progreso y reanudación

2. **Validación de Datos**
   - Análisis de schema pre-migración
   - Verificaciones de integridad de datos post-migración
   - Reconciliación de conteo de registros

3. **Manejo de Errores**
   - Recuperación elegante de fallos
   - Logging detallado de errores
   - Mecanismos de rollback

4. **Monitoreo y Reportes**
   - Dashboard de progreso de migración
   - Métricas de rendimiento
   - Reportes de calidad de datos

## 🔑 Comandos Útiles

### Configuración del Entorno
```bash
# Crear entorno virtual
python -m venv mongomigra

# Activar (Windows)
mongomigra\Scripts\activate

# Activar (Linux/Mac)
source mongomigra/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### Operaciones de Base de Datos
```bash
# Ejecutar migración
python mongomigra.py

# Verificar schema de PostgreSQL
psql -U <usuario> -d mesamongo -c "\dn"

# Verificar tablas en schema
psql -U <usuario> -d mesamongo -c "\dt lml_processes.*"

# Contar registros migrados
psql -U <usuario> -d mesamongo -c "SELECT COUNT(*) FROM lml_processes.main;"
```

### Desarrollo
```bash
# Agregar nueva dependencia
pip install <paquete>
pip freeze > requirements.txt

# Actualizar configuración
# Editar .env para secretos
# Editar config.py para parámetros no sensibles
```

## 🔐 Configuración del Entorno

### Estructura de `.env`
```ini
# MongoDB
MONGO_HOST=
MONGO_PORT=
MONGO_USER=
MONGO_PASSWORD=
MONGO_AUTH_SOURCE=

# PostgreSQL
POSTGRES_DB=mesamongo
POSTGRES_HOST=
POSTGRES_PORT=
POSTGRES_USER=
POSTGRES_PASSWORD=
```

**Nota de Seguridad**: Nunca hacer commit de `.env` al control de versiones. Usar plantilla `.env.example` para compartir con el equipo.

## 📝 Principios de Diseño Aplicados

### 1. Única Fuente de Verdad
Las entidades compartidas viven en el schema `public`, referenciadas por todos los schemas de colección vía claves foráneas.

### 2. Idempotencia
Todas las operaciones usan `ON CONFLICT DO NOTHING` para manejar re-ejecuciones de forma segura.

### 3. Rendimiento Primero
Operaciones de caché y por lotes minimizan viajes de ida y vuelta a la base de datos.

### 4. Claridad Semántica
Los nombres reflejan significado de negocio (`process_id`) no origen técnico (`mongo_id`).

### 5. Separación de Responsabilidades
- `config.py` - Configuración
- `mongomigra.py` - Lógica de migración
- `.env` - Secretos

### 6. Arquitectura A Prueba de Futuro
El diseño de schema híbrido escala a múltiples colecciones sin conflictos.

## 🎓 Lecciones Aprendidas

### Insights Técnicos
1. **Procesamiento por Lotes**: Mejora de rendimiento de 250x sobre fila por fila
2. **Caché en Memoria**: Esencial para búsquedas de entidades repetidas
3. **Timeouts de Cursor**: Operaciones de larga duración necesitan manejo explícito de timeout
4. **Claves Foráneas**: Refuerzan integridad de datos pero requieren orden de inserción cuidadoso

### Insights Arquitectónicos
1. **Schemas Híbridos**: Lo mejor de dos mundos (organización + entidades compartidas)
2. **Nomenclatura Semántica**: Reduce carga cognitiva y mejora mantenibilidad
3. **Externalización de Configuración**: Habilita flexibilidad sin cambios de código
4. **Scripts Idempotentes**: Seguridad en desarrollo y producción

## 🔄 Historial de Cambios Importantes

### v2.0 - Refactorización de Nomenclatura Semántica
**Fecha**: 2025-11-05

**Cambios**:
- Renombrado de base de datos: `postgres` → `mesamongo`
- Renombrado de columna: `mongo_id` → `process_id`
- Renombrado de FK: `record_id` → `process_id` (en todas las tablas relacionadas)
- Movimiento de entidad: `customer_id` de columna simple a FK → `public.customers`

**Justificación**: Mejorar la claridad semántica y establecer patrones de nomenclatura consistentes para futuras colecciones.

### v1.0 - Implementación Inicial de POC
**Fecha**: 2025-10-30 (aproximado)

**Logros**:
- Migración exitosa de primera colección
- Implementación de arquitectura de schema híbrido
- Optimizaciones de rendimiento (caché + batching)
- Manejo de timeout de cursor

---

**Última Actualización**: 2025-11-05  
**Versión Actual**: v2.0 (Post-refactorización con nomenclatura semántica)  
**Estado**: Listo para producción de colección única, necesita refactorización de setup para multi-colección  
**Colecciones Migradas**: 1 de ~N (pendiente determinar total)