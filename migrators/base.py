"""
Módulo base para migradores de colecciones MongoDB → PostgreSQL.

Define la interfaz común (contrato) que todos los migradores específicos
deben implementar. Esto permite que mongomigra.py funcione con cualquier
migrador sin conocer sus detalles internos.

Patrón de diseño: Strategy Pattern
- mongomigra.py = Contexto (orquestador)
- BaseMigrator = Estrategia abstracta
- LMLProcessesMigrator, LMLListbuilderMigrator = Estrategias concretas

Flujo de uso:
1. mongomigra.py carga dinámicamente un migrador
2. Llama a extract_shared_entities() para procesar public.*
3. Llama a extract_data() para obtener datos estructurados
4. Acumula en batches
5. Llama a insert_batches() para bulk insert

Ejemplo de implementación:
    class MiMigrador(BaseMigrator):
        def extract_shared_entities(self, doc, cursor, caches):
            # Lógica específica de mi colección
            return {'customer_id': '...', ...}
        
        # ... implementar resto de métodos abstractos
"""

from abc import ABC, abstractmethod


class BaseMigrator(ABC):
    """
    Clase abstracta que define la interfaz para migradores de colecciones.
    
    Cada colección (lml_processes, lml_listbuilder, etc.) debe tener un
    migrador que herede de esta clase e implemente todos sus métodos.
    
    Attributes:
        schema (str): Nombre del schema de PostgreSQL destino
    """
    
    def __init__(self, schema: str):
        """
        Constructor base que almacena el schema destino.
        
        Args:
            schema: Nombre del schema en PostgreSQL (ej: 'lml_processes')
        """
        self.schema = schema
    
    @abstractmethod
    def extract_shared_entities(self, doc: dict, cursor, caches: dict) -> dict:
        """
        Extrae y procesa entidades compartidas (public.*).
        
        Esta función debe:
        1. Extraer usuarios, customers, areas, etc. del documento
        2. Insertarlos en public.* usando ON CONFLICT DO NOTHING
        3. Usar 'caches' para evitar procesamiento redundante
        4. Retornar IDs de las entidades para usar en FKs
        
        Args:
            doc: Documento de MongoDB (dict)
            cursor: Cursor de psycopg2 para ejecutar INSERTs
            caches: Dict de sets para tracking de IDs ya procesados
                    Ej: {'users': set(), 'customers': set(), ...}
        
        Returns:
            dict: IDs de entidades procesadas, estructura:
                {
                    'customer_id': str,
                    'created_by_user_id': str|None,
                    'updated_by_user_id': str|None
                }
        
        Ejemplo de implementación:
            def extract_shared_entities(self, doc, cursor, caches):
                customer_id = doc.get('customerId')
                if customer_id not in caches['customers']:
                    cursor.execute(
                        "INSERT INTO public.customers (id) VALUES (%s) ON CONFLICT DO NOTHING",
                        (customer_id,)
                    )
                    caches['customers'].add(customer_id)
                
                return {'customer_id': customer_id, ...}
        """
        pass
    
    @abstractmethod
    def extract_data(self, doc: dict, shared_entities: dict) -> dict:
        """
        Extrae datos específicos de la colección desde un documento.
        
        Esta función convierte un documento MongoDB en una estructura
        normalizada lista para insertar en PostgreSQL. Debe retornar
        tanto el registro principal como los registros relacionados.
        
        Args:
            doc: Documento de MongoDB
            shared_entities: Dict con IDs retornados por extract_shared_entities()
        
        Returns:
            dict: Estructura con dos niveles:
                {
                    'main': tuple con valores para tabla main,
                    'related': {
                        'tabla1': [tuple, tuple, ...],
                        'tabla2': [tuple, ...],
                        ...
                    }
                }
        
        Ejemplo para lml_processes:
            {
                'main': (process_id, process_number, ...),
                'related': {
                    'movements': [(process_id, timestamp, ...), ...],
                    'documents': [(process_id, doc_id), ...]
                }
            }
        
        Ejemplo para lml_listbuilder:
            {
                'main': (listbuilder_id, alias, ...),
                'related': {
                    'fields': [(listbuilder_id, field_key, ...), ...],
                    'items': [(listbuilder_id, item_name), ...]
                }
            }
        """
        pass
    
    @abstractmethod
    def insert_batches(self, batches: dict, cursor):
        """
        Inserta todos los batches acumulados en PostgreSQL.
        
        Esta función recibe batches acumulados (resultado de múltiples
        llamadas a extract_data()) y ejecuta los INSERTs correspondientes.
        Debe manejar tanto la tabla main como todas las relacionadas.
        
        Args:
            batches: Dict con estructura:
                {
                    'main': [tuple, tuple, ...],
                    'related': {
                        'tabla1': [tuple, tuple, ...],
                        'tabla2': [tuple, ...],
                        ...
                    }
                }
            cursor: Cursor de psycopg2 para ejecutar INSERTs
        
        Responsabilidades:
        - Ejecutar executemany() para cada tipo de registro
        - Usar ON CONFLICT para idempotencia
        - Incluir el schema en las queries (ej: lml_processes.main)
        
        Ejemplo de implementación:
            def insert_batches(self, batches, cursor):
                if batches['main']:
                    cursor.executemany(
                        f"INSERT INTO {self.schema}.main (...) VALUES (...) ON CONFLICT DO NOTHING",
                        batches['main']
                    )
                
                for table_name, records in batches['related'].items():
                    if records:
                        # Construir y ejecutar INSERT para cada tabla
                        ...
        """
        pass
    
    @abstractmethod
    def initialize_batches(self) -> dict:
        """
        Retorna estructura vacía para acumular batches.
        
        La estructura retornada debe ser compatible con:
        1. extract_data() - Los registros extraídos se acumulan aquí
        2. insert_batches() - Recibe esta estructura para insertar
        
        Returns:
            dict: Estructura vacía con misma forma que extract_data():
                {
                    'main': [],
                    'related': {
                        'tabla1': [],
                        'tabla2': [],
                        ...
                    }
                }
        
        Ejemplo para lml_processes:
            {
                'main': [],
                'related': {
                    'movements': [],
                    'initiator_fields': [],
                    'documents': [],
                    'last_movements': []
                }
            }
        """
        pass
    
    @abstractmethod
    def get_primary_key_from_doc(self, doc: dict) -> str:
        """
        Extrae el valor de la primary key desde un documento MongoDB.
        
        Esta función debe saber cómo obtener el identificador único del
        documento que se usará como PK en PostgreSQL.
        
        Args:
            doc: Documento de MongoDB
        
        Returns:
            str: Valor de la primary key (ej: process_id, listbuilder_id)
        
        Ejemplo de implementación para lml_processes:
            def get_primary_key_from_doc(self, doc):
                # MongoDB ObjectId puede venir como objeto o string
                _id = doc.get('_id')
                if isinstance(_id, dict) and '$oid' in _id:
                    return _id['$oid']
                return str(_id)
        
        Nota: Aunque MongoDB use _id, en PostgreSQL puede llamarse diferente
              (process_id, listbuilder_id). Esta función retorna el VALOR,
              no el nombre de la columna.
        """
        pass