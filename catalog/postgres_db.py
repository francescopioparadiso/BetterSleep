import sys
import psycopg2
from psycopg2.extras import RealDictCursor

class PostgresDB:
    def __init__(self, db_conf):
        self.db_conf = db_conf
        # Test rapido connessione
        if not self._execute("SELECT 1"):
            print("Errore critico: Impossibile connettersi al DB.")
            sys.exit(1)
        print("Connessione PostgreSQL riuscita.")

    def connect(self):
        return psycopg2.connect(**self.db_conf)

    def _execute(self, query, params=None):
        """
        Metodo helper privato che gestisce apertura, chiusura,
        commit e rollback. Ritorna True se va a buon fine.
        """
        conn = None
        try:
            conn = self.connect()
            # 'with conn' gestisce il commit automatico se tutto va bene,
            # o il rollback se c'è un errore.
            with conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return cur.rowcount > 0 or True # True se la query non restituisce righe ma ha successo
        except psycopg2.IntegrityError:
            print("Errore: Chiave duplicata o violazione vincolo.")
            return False
        except Exception as e:
            print(f"Errore SQL generico: {e}")
            return False
        finally:
            if conn: conn.close()

    def insert_service(self, s):
        query = """
            INSERT INTO services (service_id, rest_endpoint, mqtt_topic, timestamp)
            VALUES (%s, %s, %s, %s)
        """
        # Una sola riga per eseguire tutto!
        return self._execute(query, (s['serviceID'], s['REST_endpoint'], s['MQTT_topic'], s['timestamp']))

    def update_service(self, s):
        query = """
            UPDATE services
            SET rest_endpoint = %s, mqtt_topic = %s, timestamp = %s
            WHERE service_id = %s
        """
        return self._execute(query, (s['REST_endpoint'], s['MQTT_topic'], s['timestamp'], s['serviceID']))
    def delete_service(self, service_id):
        query = "DELETE FROM services WHERE service_id = %s"
        return self._execute(query, (service_id,))
