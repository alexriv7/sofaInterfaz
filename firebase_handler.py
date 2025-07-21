import firebase_admin
from firebase_admin import credentials, db
from pathlib import Path
from datetime import datetime

class FirebaseManager:
    def __init__(self):
        """Inicializa la conexión con Firebase Realtime Database"""
        self.notification_callback = None
        self.cred_path = Path(__file__).parent / "firebase-key.json"

        if not self.cred_path.exists():
            raise FileNotFoundError("Archivo de credenciales Firebase no encontrado")

        self.cred = credentials.Certificate(str(self.cred_path))
        firebase_admin.initialize_app(self.cred, {
            'databaseURL': 'https://interfaz-en-tiempo-real-default-rtdb.firebaseio.com/'
        })
        self.ref = db.reference('/sofa_comments')

    def set_notification_callback(self, callback):
        """Configura la función a llamar cuando llegue una notificación"""
        self.notification_callback = callback

    def _normalize_path(self, path: str) -> str:
        """
        Convierte rutas de Windows a formato válido para Firebase
        Reemplaza caracteres especiales que no son permitidos como keys en Firebase
        """
        return (path
                .replace("\\", "_slash_")
                .replace(".", "_dot_")
                .replace("#", "_hash_")
                .replace("$", "_dollar_")
                .replace("[", "_lbracket_")
                .replace("]", "_rbracket_")
                .replace("/", "_fwslash_"))

    def save_comment(self, example_name: str, user: str, text: str, parent_id: str = None) -> None:
        """
        Guarda un comentario en Firebase asociado a un ejemplo

        Args:
            example_name: Nombre/ruta del ejemplo SOFA
            user: Nombre del usuario que hace el comentario
            text: Contenido del comentario
            parent_id: ID del comentario padre para hilos (opcional)
        """
        safe_path = self._normalize_path(example_name)
        comment_data = {
            "user": user,
            "text": text,
            "timestamp": {'.sv': 'timestamp'},  # Usa server timestamp de Firebase
            "original_path": example_name,
            "parent_id": parent_id
        }
        self.ref.child(safe_path).push().set(comment_data)

    def update_comment(self, example_name: str, comment_id: str, new_text: str) -> None:
        """
        Actualiza el texto de un comentario existente

        Args:
            example_name: Nombre/ruta del ejemplo SOFA
            comment_id: ID del comentario a actualizar
            new_text: Nuevo texto para el comentario
        """
        safe_path = self._normalize_path(example_name)
        self.ref.child(safe_path).child(comment_id).update({
            "text": new_text,
            "edited_timestamp": {'.sv': 'timestamp'}
        })

    def delete_comment(self, example_name: str, comment_id: str) -> None:
        """
        Borra un comentario dado su ID

        Args:
            example_name: Nombre/ruta del ejemplo SOFA
            comment_id: ID del comentario a borrar
        """
        safe_path = self._normalize_path(example_name)
        self.ref.child(safe_path).child(comment_id).delete()

    def get_comments(self, example_name: str) -> dict:
        """
        Obtiene todos los comentarios para un ejemplo específico

        Args:
            example_name: Nombre/ruta del ejemplo SOFA

        Returns:
            Dict con todos los comentarios o dict vacío si no hay
        """
        safe_path = self._normalize_path(example_name)
        return self.ref.child(safe_path).get() or {}

    def listen_updates(self, example_name: str, callback: callable):
        """
        Configura un listener en tiempo real para cambios en los comentarios

        Args:
            example_name: Nombre/ruta del ejemplo SOFA a monitorear
            callback: Función a ejecutar cuando hay cambios (recibe los nuevos datos)
        """
        safe_path = self._normalize_path(example_name)

        def listener(event):
            if event.data:  # Ignora eventos de borrado
                if (event.event_type == 'put' and event.path is not None and
                    self.notification_callback and isinstance(event.data, dict)):

                    if 'user' in event.data and 'text' in event.data:
                        self.notification_callback(
                            example_name,
                            event.data['user'],
                            event.data['text']
                        )
                callback(self.ref.child(safe_path).get())

        self.ref.child(safe_path).listen(listener)