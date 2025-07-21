import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import os
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db
from pathlib import Path
from plyer import notification
from PIL import Image, ImageTk

class FirebaseManager:
    def __init__(self):
        self.cred_path = Path(__file__).parent / "firebase-key.json"
        self.notification_callback = None
        if not self.cred_path.exists():
            raise FileNotFoundError("Archivo de credenciales Firebase no encontrado")
        self.cred = credentials.Certificate(str(self.cred_path))
        firebase_admin.initialize_app(self.cred, {
            'databaseURL': 'https://interfaz-en-tiempo-real-default-rtdb.firebaseio.com/'
        })
        self.ref = db.reference('/sofa_comments')

    def set_notification_callback(self, callback):
        self.notification_callback = callback

    def _normalize_path(self, path: str) -> str:
        return (path.replace("\\", "_slash_")
                    .replace(".", "_dot_")
                    .replace("$", "_dollar_")
                    .replace("#", "_hash_")
                    .replace("[", "_lbracket_")
                    .replace("]", "_rbracket_")
                    .replace("/", "_fwslash_"))

    def save_comment(self, example_name: str, user: str, text: str, parent_id: str = None) -> None:
        safe_path = self._normalize_path(example_name)
        comment_data = {
            "user": user,
            "text": text,
            "timestamp": {'.sv': 'timestamp'},
            "original_path": example_name,
            "parent_id": parent_id
        }
        self.ref.child(safe_path).push().set(comment_data)

    def update_comment(self, example_name: str, comment_id: str, new_text: str) -> None:
        safe_path = self._normalize_path(example_name)
        self.ref.child(safe_path).child(comment_id).update({
            "text": new_text,
            "edited_timestamp": {'.sv': 'timestamp'}
        })

    def delete_comment(self, example_name: str, comment_id: str) -> None:
        safe_path = self._normalize_path(example_name)
        self.ref.child(safe_path).child(comment_id).delete()

    def get_comments(self, example_name: str) -> dict:
        safe_path = self._normalize_path(example_name)
        return self.ref.child(safe_path).get() or {}

    def listen_updates(self, example_name: str, callback: callable):
        safe_path = self._normalize_path(example_name)
        def listener(event):
            if event.data:
                if event.event_type == 'put' and event.path is not None:
                    if self.notification_callback and isinstance(event.data, dict) and 'user' in event.data:
                        self.notification_callback(
                            example_name,
                            event.data['user'],
                            event.data['text']
                        )
                callback(self.ref.child(safe_path).get())
        self.ref.child(safe_path).listen(listener)

class SOFAInterface:
    def __init__(self, root):
        self.root = root
        self.history_file = "sofa_history.json"
        self.sofa_executable = r"C:\Users\alexr\anaconda3\envs\sofa\Library\bin\runSofa.exe"
        self.examples_dir = r"C:\Users\alexr\anaconda3\envs\sofa\Library\share\sofa\examples"
        self.current_user = os.getlogin()
        self.current_example = None
        self.notification_enabled = True
        self.unread_comments = 0
        self.editing_comment_id = None
        self.replying_to_comment_id = None
        self.current_comments = {}

        try:
            self.firebase = FirebaseManager()
            self.firebase_status = "✅ Conectado"
        except Exception as e:
            print(f"Error Firebase: {e}")
            self.firebase = None
            self.firebase_status = "❌ Desconectado"

        self.setup_ui()
        self.setup_notifications()
        self.load_history()
        self.load_examples()
        self.verify_installation()

    def setup_ui(self):
        self.root.title("SOFA Manager v3.0 - Notificaciones")
        self.root.geometry("1000x800")
        self.root.minsize(900, 700)

        style = ttk.Style()
        style.configure("TButton", padding=6, font=('Arial', 10))
        style.configure("TLabel", font=('Arial', 10))
        style.configure("Status.TLabel", font=('Arial', 9), foreground="gray")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Pestaña de Ejemplos
        tab1 = ttk.Frame(notebook)
        notebook.add(tab1, text="Ejemplos")

        main_frame = ttk.Frame(tab1)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Lista de ejemplos (izquierda)
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(list_frame, text="Ejemplos disponibles:").pack(pady=5, anchor='w')
        self.example_list = tk.Listbox(list_frame, height=25, font=('Consolas', 9))
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.example_list.yview)
        self.example_list.configure(yscrollcommand=scrollbar.set)
        self.example_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.example_list.bind("<<ListboxSelect>>", self.show_example_comments)
        self.example_list.bind("<Double-Button-1>", lambda e: self.open_example())

        # Área de comentarios (derecha)
        comments_frame = ttk.Frame(main_frame, width=400)
        comments_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))

        ttk.Label(comments_frame, text="Notas compartidas:").pack(pady=5, anchor='w')

        # Canvas y Scrollbar para comentarios
        self.comments_canvas = tk.Canvas(comments_frame, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(comments_frame, orient="vertical", command=self.comments_canvas.yview)
        self.comments_frame = ttk.Frame(self.comments_canvas)
        
        self.comments_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.comments_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.comments_canvas.create_window((0,0), window=self.comments_frame, anchor="nw")
        
        self.comments_frame.bind("<Configure>", lambda e: self.comments_canvas.configure(
            scrollregion=self.comments_canvas.bbox("all")))

        # Área para nuevo comentario
        ttk.Label(comments_frame, text="Añadir nueva nota:").pack(pady=(10, 5), anchor='w')

        self.new_comment = tk.Text(
            comments_frame,
            height=6,
            wrap=tk.WORD,
            font=('Arial', 9)
        )
        self.new_comment.pack(fill=tk.BOTH, expand=False)
        
        btn_frame = ttk.Frame(comments_frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))

        self.btn_save = ttk.Button(btn_frame, text="Guardar Nota", command=self.save_comment)
        self.btn_save.pack(side=tk.LEFT, padx=2)

        self.btn_cancel = ttk.Button(btn_frame, text="Cancelar", command=self.cancel_edit_or_reply)
        self.btn_cancel.pack(side=tk.LEFT, padx=2)
        self.btn_cancel.config(state="disabled")

        status_frame = ttk.Frame(comments_frame)
        status_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(
            status_frame,
            text=f"Usuario: {self.current_user} | Firebase: {self.firebase_status}",
            style="Status.TLabel"
        ).pack(side=tk.LEFT)

        # Pestaña de Recientes
        tab2 = ttk.Frame(notebook)
        notebook.add(tab2, text="Recientes")

        ttk.Label(tab2, text="Archivos abiertos recientemente:").pack(pady=5, anchor='w', padx=10)
        self.history_list = tk.Listbox(tab2, height=25, font=('Consolas', 9))
        scrollbar2 = ttk.Scrollbar(tab2, orient="vertical", command=self.history_list.yview)
        self.history_list.configure(yscrollcommand=scrollbar2.set)
        self.history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        scrollbar2.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10))
        self.history_list.bind("<Double-Button-1>", lambda e: self.open_from_history())

        # Botones principales
        btn_frame_main = ttk.Frame(self.root)
        btn_frame_main.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(btn_frame_main, text="Abrir ejemplo", command=self.open_example).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame_main, text="Buscar archivo...", command=self.browse_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame_main, text="Actualizar lista", command=self.load_examples).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame_main, text="Limpiar historial", command=self.clear_history).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame_main, text="Salir", command=self.root.quit).pack(side=tk.RIGHT, padx=5)

    def setup_notifications(self):
        if self.firebase:
            self.firebase.set_notification_callback(self.show_notification)

        self.notification_status = ttk.Label(
            self.root,
            text="🔔 0",
            style="Status.TLabel"
        )
        self.notification_status.pack(side=tk.RIGHT, padx=10)

        self.notification_menu = tk.Menu(self.root, tearoff=0)
        self.notification_enabled_var = tk.BooleanVar(value=self.notification_enabled)
        self.notification_menu.add_checkbutton(
            label="Activar notificaciones",
            variable=self.notification_enabled_var,
            command=self.toggle_notifications
        )
        self.notification_menu.add_command(
            label="Ver todas",
            command=self.show_all_notifications
        )

        self.notification_status.bind("<Button-3>", lambda e:
            self.notification_menu.tk_popup(e.x_root, e.y_root))

    def show_notification(self, example_name, user, comment_text):
        if not self.notification_enabled:
            return
        self.unread_comments += 1
        self.update_notification_badge()
        notification.notify(
            title=f"Nuevo comentario en {example_name}",
            message=f"{user}: {comment_text[:100]}...",
            app_name="SOFA Manager",
            timeout=10
        )

    def update_notification_badge(self):
        self.notification_status.config(text=f"🔔 {self.unread_comments}")
        self.notification_status.config(foreground="red" if self.unread_comments > 0 else "black")

    def toggle_notifications(self):
        self.notification_enabled = self.notification_enabled_var.get()
        status = "activadas" if self.notification_enabled else "desactivadas"
        messagebox.showinfo("Notificaciones", f"Notificaciones {status}")

    def show_all_notifications(self):
        self.unread_comments = 0
        self.update_notification_badge()
        messagebox.showinfo("Notificaciones", "Marcando todas como leídas")

    def update_comments_display(self, comments):
        # Limpiar el frame de comentarios
        for widget in self.comments_frame.winfo_children():
            widget.destroy()

        if not comments:
            no_comments = ttk.Label(self.comments_frame, text="No hay notas para este ejemplo.")
            no_comments.pack(pady=10)
            return
        
        self.current_comments = comments
        comments_by_id = {}
        children_map = {}

        # Organizar comentarios por parent_id
        for cid, comment in comments.items():
            comments_by_id[cid] = comment
            parent = comment.get('parent_id')
            children_map.setdefault(parent, []).append(cid)

        # Función recursiva para mostrar hilos
        def display_thread(parent_id=None, level=0):
            if parent_id not in children_map:
                return

            for cid in sorted(children_map[parent_id], 
                            key=lambda x: comments_by_id[x].get('timestamp', 0), 
                            reverse=True):
                comment = comments_by_id[cid]
                user = comment.get('user', 'Anónimo')
                text = comment.get('text', '')
                timestamp = comment.get('timestamp', 'Fecha desconocida')
                
                if isinstance(timestamp, dict):
                    timestamp = "Recién guardado"
                elif isinstance(timestamp, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

                # Frame para cada comentario
                comment_frame = ttk.Frame(self.comments_frame)
                comment_frame.pack(fill=tk.X, pady=5, padx=(10 * level, 10))

                # Cabecera del comentario
                header_frame = ttk.Frame(comment_frame)
                header_frame.pack(fill=tk.X)
                
                initials = "".join([w[0] for w in user.split() if w]).upper()[:2]
                ttk.Label(header_frame, text=f"👤[{initials}] {user}").pack(side=tk.LEFT)
                ttk.Label(header_frame, text=f"🕒 {timestamp}", style="Status.TLabel").pack(side=tk.LEFT, padx=10)

                # Texto del comentario
                ttk.Label(comment_frame, text=text, wraplength=350, anchor='w').pack(fill=tk.X)

                # Botones de acciones
                btn_frame = ttk.Frame(comment_frame)
                btn_frame.pack(fill=tk.X)
                
                if user == self.current_user:
                    ttk.Button(btn_frame, text="Editar", 
                            command=lambda cid=cid: self.start_edit_comment(cid)).pack(side=tk.LEFT, padx=2)
                    ttk.Button(btn_frame, text="Borrar", 
                            command=lambda cid=cid: self.delete_comment(cid)).pack(side=tk.LEFT, padx=2)
                
                ttk.Button(btn_frame, text="Responder", 
                        command=lambda cid=cid: self.start_reply_comment(cid)).pack(side=tk.LEFT, padx=2)

                # Comentarios hijos
                display_thread(cid, level + 1)
        
        display_thread()
        self.comments_canvas.yview_moveto(0)  # Scroll al inicio

    def start_edit_comment(self, comment_id):
        if not self.current_comments or comment_id not in self.current_comments:
            return
        comment = self.current_comments[comment_id]
        if comment.get("user") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo puedes editar tus propios comentarios.")
            return
        self.editing_comment_id = comment_id
        self.replying_to_comment_id = None
        self.new_comment.delete(1.0, tk.END)
        self.new_comment.insert(tk.END, comment.get("text", ""))
        self.btn_save.config(text="Guardar Cambios")
        self.btn_cancel.config(state="normal")

    def delete_comment(self, comment_id):
        if not self.current_comments or comment_id not in self.current_comments:
            return
        comment = self.current_comments[comment_id]
        if comment.get("user") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo puedes borrar tus propios comentarios.")
            return
        if messagebox.askyesno("Confirmar", "¿Estás seguro de borrar este comentario?"):
            try:
                self.firebase.delete_comment(self.current_example, comment_id)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo borrar el comentario:\n{e}")

    def start_reply_comment(self, comment_id):
        if not self.current_comments or comment_id not in self.current_comments:
            return
        self.replying_to_comment_id = comment_id
        self.editing_comment_id = None
        self.new_comment.delete(1.0, tk.END)
        user = self.current_comments[comment_id].get("user", "")
        self.new_comment.insert(tk.END, f"@{user} ")
        self.btn_save.config(text="Guardar Respuesta")
        self.btn_cancel.config(state="normal")

    def cancel_edit_or_reply(self):
        self.editing_comment_id = None
        self.replying_to_comment_id = None
        self.new_comment.delete(1.0, tk.END)
        self.btn_save.config(text="Guardar Nota")
        self.btn_cancel.config(state="disabled")

    def show_example_comments(self, event):
        selection = self.example_list.curselection()
        if not selection:
            return
        example_name = self.example_list.get(selection[0])
        self.current_example = example_name
        self.unread_comments = 0
        self.update_notification_badge()
        if self.firebase:
            comments = self.firebase.get_comments(example_name)
            self.update_comments_display(comments)
            self.firebase.listen_updates(example_name, self.update_comments_display)
        else:
            no_connection = ttk.Label(self.comments_frame, text="Modo offline - Sin conexión a Firebase")
            no_connection.pack(pady=10)
        self.new_comment.delete(1.0, tk.END)
        self.cancel_edit_or_reply()

    def save_comment(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero")
            return
        comment_text = self.new_comment.get("1.0", tk.END).strip()
        if not comment_text:
            messagebox.showwarning("Advertencia", "La nota no puede estar vacía")
            return
        
        try:
            if self.editing_comment_id:
                self.firebase.update_comment(self.current_example, self.editing_comment_id, comment_text)
            else:
                parent_id = self.replying_to_comment_id if self.replying_to_comment_id else None
                self.firebase.save_comment(self.current_example, self.current_user, comment_text, parent_id)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar la nota:\n{e}")
            return

        self.new_comment.delete(1.0, tk.END)
        self.cancel_edit_or_reply()

    def verify_installation(self):
        if not os.path.exists(self.sofa_executable):
            messagebox.showerror("Error", f"Ejecutable SOFA no encontrado en:\n{self.sofa_executable}")
        if not os.path.exists(self.examples_dir):
            messagebox.showerror("Error", f"Carpeta de ejemplos no encontrada en:\n{self.examples_dir}")

    def load_examples(self):
        self.example_list.delete(0, tk.END)
        if os.path.exists(self.examples_dir):
            for root, _, files in os.walk(self.examples_dir):
                for file in files:
                    if file.lower().endswith(('.scn', '.py', '.xml')):
                        rel_path = os.path.relpath(os.path.join(root, file), self.examples_dir)
                        self.example_list.insert(tk.END, rel_path)
        else:
            messagebox.showerror("Error", "Carpeta de ejemplos no encontrada")

    def browse_file(self):
        filepath = filedialog.askopenfilename(
            title="Seleccionar archivo SOFA",
            filetypes=[("Archivos SOFA", "*.scn *.py *.xml"), ("Todos los archivos", "*.*")]
        )
        if filepath:
            rel_path = os.path.relpath(filepath, self.examples_dir) if filepath.startswith(self.examples_dir) else filepath
            self.current_example = rel_path
            if rel_path not in self.example_list.get(0, tk.END):
                self.example_list.insert(tk.END, rel_path)
            self.open_example()
            self.save_to_history(filepath)

    def open_example(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero")
            return
        path = os.path.join(self.examples_dir, self.current_example)
        if not os.path.exists(path):
            path = self.current_example
            if not os.path.exists(path):
                messagebox.showerror("Error", f"No se encontró el archivo:\n{self.current_example}")
                return
        try:
            subprocess.Popen([self.sofa_executable, path])
            self.save_to_history(path)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir el ejemplo:\n{e}")

    def save_to_history(self, filepath):
        history = []
        if os.path.exists(self.history_file):
            with open(self.history_file, "r", encoding="utf-8") as f:
                try:
                    history = json.load(f)
                except:
                    history = []
        if filepath in history:
            history.remove(filepath)
        history.insert(0, filepath)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(history[:30], f, indent=2)
        self.load_history()

    def load_history(self):
        self.history_list.delete(0, tk.END)
        if os.path.exists(self.history_file):
            with open(self.history_file, "r", encoding="utf-8") as f:
                try:
                    history = json.load(f)
                    for item in history:
                        self.history_list.insert(tk.END, item)
                except:
                    pass

    def open_from_history(self):
        selection = self.history_list.curselection()
        if not selection:
            return
        path = self.history_list.get(selection[0])
        if os.path.exists(path):
            self.current_example = os.path.relpath(path, self.examples_dir) if path.startswith(self.examples_dir) else path
            self.open_example()
        else:
            messagebox.showerror("Error", f"No se encontró el archivo:\n{path}")

    def clear_history(self):
        if messagebox.askyesno("Confirmar", "¿Deseas limpiar el historial?"):
            if os.path.exists(self.history_file):
                os.remove(self.history_file)
            self.history_list.delete(0, tk.END)

def main():
    root = tk.Tk()
    app = SOFAInterface(root)
    root.mainloop()

if __name__ == "__main__":
    main()