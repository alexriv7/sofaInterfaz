import os
import firebase_admin
from firebase_admin import credentials, db
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Callable

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")


class FirebaseManager:
    def __init__(self):
        """Inicializa la conexión con Firebase Realtime Database"""
        self.notification_callback = None
        self._active_listeners: Dict[str, object] = {}
        self.cred_path = Path(__file__).parent / "firebase-key.json"

        if not self.cred_path.exists():
            raise FileNotFoundError("Archivo de credenciales Firebase no encontrado")

        database_url = os.environ.get("FIREBASE_DATABASE_URL")
        if not database_url:
            raise EnvironmentError(
                "No se encontró FIREBASE_DATABASE_URL en el archivo .env"
            )

        self.cred = credentials.Certificate(str(self.cred_path))
        if not firebase_admin._apps:
            firebase_admin.initialize_app(self.cred, {"databaseURL": database_url})

        self.ref = db.reference("/sofa_comments")
        self.groups_ref = db.reference("/sofa_groups")
        self.examples_ref = db.reference("/sofa_examples")

    def set_notification_callback(self, callback: Callable):
        """Configura la función a llamar cuando llegue una notificación"""
        self.notification_callback = callback

    # -----------------------------------------------------------------------
    # Normalización de rutas
    # -----------------------------------------------------------------------

    def _normalize_path(self, path: str) -> str:
        """Convierte rutas de Windows a formato válido para Firebase"""
        return (
            path
            .replace("\\", "_slash_")
            .replace(".", "_dot_")
            .replace("#", "_hash_")
            .replace("$", "_dollar_")
            .replace("[", "_lbracket_")
            .replace("]", "_rbracket_")
            .replace("/", "_fwslash_")
        )

    # -----------------------------------------------------------------------
    # Biblioteca de ejemplos (la consume la web app)
    # -----------------------------------------------------------------------

    def publish_examples(self, examples: list) -> None:
        """
        Publica la lista de ejemplos locales en /sofa_examples para la web app.
        Hace merge: no borra ejemplos publicados desde otras máquinas.

        Args:
            examples: Rutas relativas a la carpeta de ejemplos (p. ej. "Demos\\caduceus.scn")
        """
        data = {}
        for rel in examples:
            parts = rel.replace("\\", "/").split("/")
            name = parts[-1]
            data[self._normalize_path(rel)] = {
                "path": rel,
                "name": name,
                "folder": "/".join(parts[:-1]),
                "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
            }
        if data:
            self.examples_ref.update(data)

    # -----------------------------------------------------------------------
    # Grupos colaborativos
    # -----------------------------------------------------------------------

    def create_group(self, group_name: str, owner: str) -> str:
        """
        Crea un nuevo grupo colaborativo.

        Args:
            group_name: Nombre del grupo
            owner: Usuario creador del grupo

        Returns:
            ID del grupo creado
        """
        group_data = {
            "name": group_name,
            "owner": owner,
            "members": {owner: True},
            "created_at": {".sv": "timestamp"},
        }
        new_ref = self.groups_ref.push()
        new_ref.set(group_data)
        return new_ref.key

    def add_member(self, group_id: str, username: str) -> None:
        """
        Agrega un miembro a un grupo existente.

        Args:
            group_id: ID del grupo
            username: Nombre de usuario a agregar
        """
        self.groups_ref.child(group_id).child("members").child(username).set(True)

    def remove_member(self, group_id: str, username: str) -> None:
        """
        Elimina un miembro de un grupo.

        Args:
            group_id: ID del grupo
            username: Nombre de usuario a eliminar
        """
        self.groups_ref.child(group_id).child("members").child(username).delete()

    def delete_group(self, group_id: str) -> None:
        """Elimina completamente un grupo y sus comentarios."""
        self.groups_ref.child(group_id).delete()

    def get_my_groups(self, username: str) -> Dict[str, dict]:
        """
        Obtiene todos los grupos donde el usuario es miembro.

        Args:
            username: Nombre de usuario

        Returns:
            Dict {group_id: {name, owner, members, ...}}
        """
        all_groups = self.groups_ref.get() or {}
        my = {}
        for gid, gdata in all_groups.items():
            members = gdata.get("members", {})
            if username in members:
                my[gid] = gdata
        return my

    def get_group_info(self, group_id: str) -> Optional[dict]:
        """Obtiene la información de un grupo."""
        return self.groups_ref.child(group_id).get()

    # -----------------------------------------------------------------------
    # Comentarios (con soporte de grupos)
    # -----------------------------------------------------------------------

    def _comment_ref(self, example_name: str, group_id: Optional[str] = None):
        """Devuelve la referencia correcta según si hay grupo activo o no."""
        safe_path = self._normalize_path(example_name)
        if group_id:
            return db.reference(f"/sofa_group_comments/{group_id}/{safe_path}")
        return self.ref.child(safe_path)

    def save_comment(
        self,
        example_name: str,
        user: str,
        text: str,
        parent_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> None:
        """
        Guarda un comentario asociado a un ejemplo, opcionalmente dentro de un grupo.

        Args:
            example_name: Nombre/ruta del ejemplo SOFA
            user: Nombre del usuario
            text: Contenido del comentario
            parent_id: ID del comentario padre para hilos (opcional)
            group_id: ID del grupo (None = notas globales)
        """
        comment_data = {
            "user": user,
            "text": text,
            "timestamp": {".sv": "timestamp"},
            "original_path": example_name,
            "parent_id": parent_id,
        }
        self._comment_ref(example_name, group_id).push().set(comment_data)

    def update_comment(
        self,
        example_name: str,
        comment_id: str,
        new_text: str,
        group_id: Optional[str] = None,
    ) -> None:
        """Actualiza el texto de un comentario existente."""
        self._comment_ref(example_name, group_id).child(comment_id).update(
            {"text": new_text, "edited_timestamp": {".sv": "timestamp"}}
        )

    def delete_comment(
        self, example_name: str, comment_id: str, group_id: Optional[str] = None
    ) -> None:
        """Borra un comentario dado su ID."""
        self._comment_ref(example_name, group_id).child(comment_id).delete()

    def get_comments(
        self, example_name: str, group_id: Optional[str] = None
    ) -> dict:
        """
        Obtiene todos los comentarios para un ejemplo.

        Args:
            example_name: Nombre/ruta del ejemplo SOFA
            group_id: ID del grupo (None = notas globales)

        Returns:
            Dict con todos los comentarios o dict vacío si no hay
        """
        return self._comment_ref(example_name, group_id).get() or {}

    def listen_updates(
        self,
        example_name: str,
        callback: Callable,
        group_id: Optional[str] = None,
    ):
        """
        Configura un listener en tiempo real para cambios en los comentarios.
        Cierra el listener anterior para el mismo ejemplo si existe.

        Args:
            example_name: Nombre/ruta del ejemplo SOFA
            callback: Función a ejecutar cuando hay cambios
            group_id: ID del grupo (None = notas globales)
        """
        listener_key = f"{group_id or 'global'}::{example_name}"

        # Cerrar listener previo para evitar acumulación
        if listener_key in self._active_listeners:
            try:
                self._active_listeners[listener_key].close()
            except Exception:
                pass

        ref = self._comment_ref(example_name, group_id)

        def listener(event):
            if event.data:
                if (
                    event.event_type == "put"
                    and event.path is not None
                    and self.notification_callback
                    and isinstance(event.data, dict)
                ):
                    if "user" in event.data and "text" in event.data:
                        self.notification_callback(
                            example_name,
                            event.data["user"],
                            event.data["text"],
                        )
                callback(ref.get())

        handle = ref.listen(listener)
        self._active_listeners[listener_key] = handle
