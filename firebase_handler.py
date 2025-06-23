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

    def save_comment(self, example_name: str, user: str, text: str) -> None:
        """
        Guarda un comentario en Firebase asociado a un ejemplo
        
        Args:
            example_name: Nombre/ruta del ejemplo SOFA
            user: Nombre del usuario que hace el comentario
            text: Contenido del comentario
        """
        safe_path = self._normalize_path(example_name)
        comment_data = {
            "user": user,
            "text": text,
            "timestamp": {'.sv': 'timestamp'},  # Usa server timestamp de Firebase
            "original_path": example_name  # Guardamos la ruta original para referencia
        }
        self.ref.child(safe_path).push().set(comment_data)
    
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
                # Notificar solo si es un nuevo comentario (no una actualización)
                if (event.event_type == 'put' and event.path is not None and 
                    self.notification_callback and isinstance(event.data, dict)):
                    
                    # Extraer el nuevo comentario específico
                    new_comment = event.data
                    if 'user' in new_comment and 'text' in new_comment:
                        self.notification_callback(
                            example_name,
                            new_comment['user'],
                            new_comment['text']
                        )
                
                # Llamar al callback principal en cualquier caso
                callback(self.ref.child(safe_path).get())

        self.ref.child(safe_path).listen(listener)