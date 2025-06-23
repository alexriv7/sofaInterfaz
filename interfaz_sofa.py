import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess
import os
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db
from pathlib import Path
from plyer import notification
import tempfile
from PIL import Image, ImageTk
import threading


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
        return (
            path.replace("\\", "_slash_")
               .replace(".", "_dot_")
               .replace("$", "_dollar_")
               .replace("#", "_hash_")
               .replace("[", "_lbracket_")
               .replace("]", "_rbracket_")
               .replace("/", "_fwslash_")
        )
    
    def save_comment(self, example_name: str, user: str, text: str) -> None:
        safe_path = self._normalize_path(example_name)
        comment_data = {
            "user": user,
            "text": text,
            "timestamp": {'.sv': 'timestamp'},
            "original_path": example_name
        }
        self.ref.child(safe_path).push().set(comment_data)
    
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
        
        try:
            self.firebase = FirebaseManager()
            self.firebase_status = "✅ Conectado"
        except:
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

        tab1 = ttk.Frame(notebook)
        notebook.add(tab1, text="Ejemplos")

        main_frame = ttk.Frame(tab1)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

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

        comments_frame = ttk.Frame(main_frame, width=350)
        comments_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))

        ttk.Label(comments_frame, text="Notas compartidas:").pack(pady=5, anchor='w')
        
        self.comments_display = scrolledtext.ScrolledText(
            comments_frame, 
            wrap=tk.WORD,
            width=45,
            height=15,
            font=('Arial', 9),
            state='disabled'
        )
        self.comments_display.pack(fill=tk.BOTH, expand=True)
        
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
        
        ttk.Button(
            btn_frame,
            text="Guardar Nota",
            command=self.save_comment
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            btn_frame,
            text="Limpiar",
            command=self.clear_comment
        ).pack(side=tk.LEFT, padx=2)
        
        status_frame = ttk.Frame(comments_frame)
        status_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(
            status_frame,
            text=f"Usuario: {self.current_user} | Firebase: {self.firebase_status}",
            style="Status.TLabel"
        ).pack(side=tk.LEFT)

        tab2 = ttk.Frame(notebook)
        notebook.add(tab2, text="Recientes")

        ttk.Label(tab2, text="Archivos abiertos recientemente:").pack(pady=5, anchor='w', padx=10)
        self.history_list = tk.Listbox(tab2, height=25, font=('Consolas', 9))
        scrollbar2 = ttk.Scrollbar(tab2, orient="vertical", command=self.history_list.yview)
        self.history_list.configure(yscrollcommand=scrollbar2.set)
        self.history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        scrollbar2.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10))
        self.history_list.bind("<Double-Button-1>", lambda e: self.open_from_history())

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(btn_frame, text="Abrir ejemplo", command=self.open_example).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Buscar archivo...", command=self.browse_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Actualizar lista", command=self.load_examples).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Limpiar historial", command=self.clear_history).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Salir", command=self.root.quit).pack(side=tk.RIGHT, padx=5)

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
        self.notification_menu.add_checkbutton(
            label="Activar notificaciones",
            variable=tk.BooleanVar(value=self.notification_enabled),
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
        self.notification_enabled = not self.notification_enabled
        status = "activadas" if self.notification_enabled else "desactivadas"
        messagebox.showinfo("Notificaciones", f"Notificaciones {status}")

    def show_all_notifications(self):
        self.unread_comments = 0
        self.update_notification_badge()
        messagebox.showinfo("Notificaciones", "Marcando todas como leídas")

    def display_comment(self, comment):
        self.comments_display.config(state=tk.NORMAL)
        timestamp = comment.get('timestamp', 'Fecha desconocida')
        
        if isinstance(timestamp, dict):
            timestamp = "Recién guardado"
        elif isinstance(timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')
        
        self.comments_display.insert(tk.END,
            f"👤 {comment.get('user', 'Anónimo')}\n"
            f"🕒 {timestamp}\n"
            f"📝 {comment.get('text', '')}\n\n"
            + "-"*50 + "\n\n"
        )
        self.comments_display.config(state=tk.DISABLED)

    def update_comments_display(self, comments):
        self.comments_display.config(state=tk.NORMAL)
        self.comments_display.delete(1.0, tk.END)
        
        if comments:
            for comment_id, comment in comments.items():
                self.display_comment(comment)
        else:
            self.comments_display.insert(tk.END, "No hay notas para este ejemplo.\n")
        
        self.comments_display.config(state=tk.DISABLED)

    def show_example_comments(self, event):
        selection = self.example_list.curselection()
        if not selection:
            return
            
        example_name = self.example_list.get(selection[0])
        self.current_example = example_name
        
        self.unread_comments = 0
        self.update_notification_badge()
        
        self.comments_display.config(state=tk.NORMAL)
        self.comments_display.delete(1.0, tk.END)
        self.comments_display.insert(tk.END, f"Comentarios para:\n{example_name}\n\n")
        
        if self.firebase:
            comments = self.firebase.get_comments(example_name)
            if comments:
                for comment_id, comment in comments.items():
                    self.display_comment(comment)
            else:
                self.comments_display.insert(tk.END, "No hay notas para este ejemplo.\n")
            
            self.firebase.listen_updates(example_name, self.update_comments_display)
        else:
            self.comments_display.insert(tk.END, "Modo offline - Sin conexión a Firebase\n")
        
        self.comments_display.config(state=tk.DISABLED)
        self.new_comment.delete(1.0, tk.END)

    def save_comment(self):
        if not hasattr(self, 'current_example') or not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero")
            return
            
        comment_text = self.new_comment.get("1.0", tk.END).strip()
        if not comment_text:
            messagebox.showwarning("Advertencia", "La nota no puede estar vacía")
            return
            
        if self.firebase:
            self.firebase.save_comment(
                example_name=self.current_example,
                user=self.current_user,
                text=comment_text
            )
            self.new_comment.delete(1.0, tk.END)

    def clear_comment(self):
        self.new_comment.delete(1.0, tk.END)

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
                        rel_path = os.path.relpath(os.path.join(root, file), start=self.examples_dir)
                        self.example_list.insert(tk.END, rel_path)

    def load_history(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, "r") as f:
                history = json.load(f)
                for item in history:
                    if os.path.exists(item):
                        self.history_list.insert(tk.END, item)

    def save_to_history(self, filepath):
        current_items = list(self.history_list.get(0, tk.END))
        
        if filepath in current_items:
            self.history_list.delete(current_items.index(filepath))
        
        self.history_list.insert(0, filepath)
        
        if self.history_list.size() > 15:
            self.history_list.delete(15, tk.END)
        
        with open(self.history_file, "w") as f:
            json.dump(list(self.history_list.get(0, tk.END)), f)

    def open_example(self):
        selection = self.example_list.curselection()
        if not selection:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero")
            return
            
        example_rel = self.example_list.get(selection[0])
        full_path = os.path.normpath(os.path.join(self.examples_dir, example_rel))
        
        if os.path.exists(full_path):
            self.launch_sofa(full_path)

    def browse_file(self):
        filepath = filedialog.askopenfilename(
            title="Seleccionar archivo SOFA",
            filetypes=[("Archivos SOFA", "*.scn *.py *.xml"), ("Todos los archivos", "*.*")],
            initialdir=self.examples_dir
        )
        
        if filepath:
            self.launch_sofa(filepath)

    def open_from_history(self):
        selection = self.history_list.curselection()
        if selection:
            filepath = self.history_list.get(selection[0])
            if os.path.exists(filepath):
                self.launch_sofa(filepath)

    def launch_sofa(self, filepath):
        if not os.path.exists(self.sofa_executable):
            messagebox.showerror("Error", f"El ejecutable de SOFA no existe en:\n{self.sofa_executable}")
            return

        self.save_to_history(filepath)
        subprocess.Popen(
            [
                self.sofa_executable,
                "-l", "Sofa.GUI.Qt",
                "-g", "qt",
                "-l", "SofaPython3",
                filepath
            ],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            shell=True
        )

    def clear_history(self):
        if messagebox.askyesno("Confirmar", "¿Borrar todo el historial?"):
            self.history_list.delete(0, tk.END)
            if os.path.exists(self.history_file):
                os.remove(self.history_file)

if __name__ == "__main__":
    root = tk.Tk()
    app = SOFAInterface(root)
    root.mainloop()