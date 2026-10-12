"""
interfaz_sofa.py
Interfaz gráfica para gestionar simulaciones SOFA Framework.
Requiere: firebase_handler.py y firebase-key.json en el mismo directorio.
"""

import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from plyer import notification

from firebase_handler import FirebaseManager


# ---------------------------------------------------------------------------
# Detección automática de la instalación de SOFA
# ---------------------------------------------------------------------------

def _find_sofa_installation() -> tuple:
    """
    Busca runSofa.exe y la carpeta de ejemplos en las rutas más comunes.
    Devuelve (ejecutable, carpeta_ejemplos) con los primeros encontrados,
    o cadenas vacías si no se encuentran.
    """
    candidate_roots = []

    conda_base_candidates = [
        Path.home() / "anaconda3",
        Path.home() / "miniconda3",
        Path("C:/ProgramData/Anaconda3"),
        Path("C:/ProgramData/miniconda3"),
    ]
    for base in conda_base_candidates:
        envs_dir = base / "envs"
        if envs_dir.exists():
            for env in envs_dir.iterdir():
                candidate_roots.append(env / "Library")
        candidate_roots.append(base / "Library")

    for pf in ["C:/Program Files/SOFA", "C:/Program Files (x86)/SOFA"]:
        p = Path(pf)
        if p.exists():
            candidate_roots.append(p)

    exe_path = ""
    examples_path = ""

    for root in candidate_roots:
        exe = root / "bin" / "runSofa.exe"
        if exe.exists() and not exe_path:
            exe_path = str(exe)

        examples = root / "share" / "sofa" / "examples"
        if examples.exists() and not examples_path:
            examples_path = str(examples)

        if exe_path and examples_path:
            break

    return exe_path, examples_path


# ---------------------------------------------------------------------------
# Interfaz principal
# ---------------------------------------------------------------------------

class SOFAInterface:
    def __init__(self, root: tk.Tk):
        self.root = root

        # --- Archivos de datos locales ---
        self.config_file  = str(Path(__file__).parent / "sofa_config.json")
        self.history_file = str(Path(__file__).parent / "sofa_history.json")
        self.tags_file    = str(Path(__file__).parent / "sofa_tags.json")
        self.favorites: set = set()
        self.tags_by_example: dict = {}
        self._show_only_favorites = False

        # --- Cargar config guardada ---
        self._load_config()
        self._load_tags_data()

        # --- Estado interno ---
        self.current_example        = None
        self.unread_comments        = 0
        self.editing_comment_id     = None
        self.replying_to_comment_id = None
        self.current_comments       = {}

        # --- Estado de grupos ---
        self.active_group_id: Optional[str] = None    # None = notas globales
        self.active_group_name: str = "Global"
        self._my_groups: Dict[str, dict] = {}

        # --- Firebase ---
        try:
            self.firebase = FirebaseManager()
            self.firebase.set_notification_callback(self._on_new_comment_notification)
            self.firebase_status = "✅ Conectado"
        except Exception as exc:
            print(f"[Firebase] Error al conectar: {exc}")
            self.firebase = None
            self.firebase_status = "❌ Desconectado"

        # --- Construir UI ---
        self._setup_ui()
        self._setup_notifications()
        self._load_history()
        self._load_examples()
        self._verify_installation()

        # Cargar grupos si Firebase está disponible
        if self.firebase:
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -----------------------------------------------------------------------
    # Construcción de la UI
    # -----------------------------------------------------------------------

    def _setup_ui(self):
        self.root.title("SOFA Manager v3.2")
        self.root.geometry("1100x800")
        self.root.minsize(900, 700)

        style = ttk.Style()
        style.configure("TButton",     padding=6,  font=("Arial", 10))
        style.configure("TLabel",                  font=("Arial", 10))
        style.configure("Status.TLabel", font=("Arial", 9), foreground="gray")
        style.configure("Reply.TFrame", background="#f0f4ff")
        style.configure("Group.TFrame", background="#eef4ee")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._build_examples_tab(notebook)
        self._build_history_tab(notebook)
        self._build_console_tab(notebook)
        self._build_groups_tab(notebook)
        self._build_settings_tab(notebook)

        # Barra de botones inferior
        btn_bar = ttk.Frame(self.root)
        btn_bar.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(btn_bar, text="▶  Abrir ejemplo",   command=self._open_example).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_bar, text="🔍 Buscar archivo…",  command=self._browse_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_bar, text="🔄 Actualizar lista", command=self._load_examples).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_bar, text="🗑  Limpiar historial", command=self._clear_history).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_bar, text="Salir",               command=self.root.quit).pack(side=tk.RIGHT, padx=5)

    def _build_examples_tab(self, notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Ejemplos")

        paned = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Panel izquierdo: lista de ejemplos ---
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="Ejemplos disponibles:").pack(anchor="w", pady=(0, 4))

        search_frame = ttk.Frame(left)
        search_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(search_frame, text="🔎").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_examples())
        ttk.Entry(search_frame, textvariable=self._search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._fav_filter_btn = ttk.Button(
            search_frame, text="☆ Favoritos", width=11,
            command=self._toggle_favorites_filter,
        )
        self._fav_filter_btn.pack(side=tk.LEFT, padx=(4, 0))

        listbox_frame = ttk.Frame(left)
        listbox_frame.pack(fill=tk.BOTH, expand=True)
        self.example_list = tk.Listbox(listbox_frame, font=("Consolas", 9))
        sb = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.example_list.yview)
        self.example_list.configure(yscrollcommand=sb.set)
        self.example_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.example_list.bind("<<ListboxSelect>>", self._show_example_comments)
        self.example_list.bind("<Double-Button-1>",  lambda e: self._open_example())

        fav_bar = ttk.Frame(left)
        fav_bar.pack(fill=tk.X, pady=(4, 0))
        self._fav_toggle_btn = ttk.Button(
            fav_bar, text="☆ Marcar como favorito",
            command=self._toggle_current_favorite,
        )
        self._fav_toggle_btn.pack(side=tk.LEFT)

        # --- Panel derecho: sub-notebook ---
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        right_nb = ttk.Notebook(right)
        right_nb.pack(fill=tk.BOTH, expand=True)

        # ---- Sub-pestaña: Vista previa ----
        preview_tab = ttk.Frame(right_nb)
        right_nb.add(preview_tab, text="📄 Vista previa")

        prev_header = ttk.Frame(preview_tab)
        prev_header.pack(fill=tk.X, padx=4, pady=(4, 2))
        self._preview_title = ttk.Label(prev_header, text="Selecciona un ejemplo.", style="Status.TLabel")
        self._preview_title.pack(side=tk.LEFT)
        ttk.Button(prev_header, text="▶ Abrir", command=self._open_example).pack(side=tk.RIGHT, padx=2)

        tags_bar = ttk.Frame(preview_tab)
        tags_bar.pack(fill=tk.X, padx=4, pady=(0, 4))

        self._tags_chip_frame = ttk.Frame(tags_bar)
        self._tags_chip_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._new_tag_var = tk.StringVar()
        tag_entry = ttk.Entry(tags_bar, textvariable=self._new_tag_var, width=14)
        tag_entry.pack(side=tk.RIGHT)
        tag_entry.bind("<Return>", lambda e: self._add_tag_to_current())
        ttk.Button(tags_bar, text="+ Tag", width=6, command=self._add_tag_to_current).pack(side=tk.RIGHT, padx=(0, 4))

        prev_frame = ttk.Frame(preview_tab)
        prev_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self.preview_canvas = tk.Canvas(prev_frame, bg="#1e1e1e", highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self._preview_image_ref = None

        self._preview_no_img_id = self.preview_canvas.create_text(
            10, 10,
            anchor="nw",
            text="Selecciona un ejemplo.",
            fill="#666666",
            font=("Arial", 10),
        )

        ttk.Button(
            preview_tab,
            text="📂 Asignar imagen a este ejemplo",
            command=self._assign_preview_image,
        ).pack(anchor="w", padx=4, pady=(0, 4))

        # ---- Sub-pestaña: Notas ----
        notes_tab = ttk.Frame(right_nb)
        right_nb.add(notes_tab, text="🗒 Notas")

        # Selector de grupo activo
        group_sel_frame = ttk.Frame(notes_tab)
        group_sel_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(group_sel_frame, text="Grupo activo:").pack(side=tk.LEFT)
        self._active_group_label = ttk.Label(
            group_sel_frame, text="🌐 Global", style="Status.TLabel"
        )
        self._active_group_label.pack(side=tk.LEFT, padx=6)
        ttk.Button(
            group_sel_frame, text="👥 Cambiar grupo",
            command=self._show_group_picker,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Label(notes_tab, text="Notas compartidas:").pack(anchor="w", pady=(2, 2), padx=4)

        canvas_frame = ttk.Frame(notes_tab)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4)

        self.comments_canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0)
        comments_sb = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.comments_canvas.yview)
        self.comments_canvas.configure(yscrollcommand=comments_sb.set)
        comments_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.comments_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.comments_inner = ttk.Frame(self.comments_canvas)
        self._canvas_window_id = self.comments_canvas.create_window(
            (0, 0), window=self.comments_inner, anchor="nw"
        )
        self.comments_inner.bind(
            "<Configure>",
            lambda e: self.comments_canvas.configure(
                scrollregion=self.comments_canvas.bbox("all")
            ),
        )
        self.comments_canvas.bind(
            "<Configure>",
            lambda e: self.comments_canvas.itemconfig(
                self._canvas_window_id, width=e.width
            ),
        )

        ttk.Separator(notes_tab, orient="horizontal").pack(fill=tk.X, pady=4, padx=4)
        self._reply_label = ttk.Label(notes_tab, text="Añadir nueva nota:", style="Status.TLabel")
        self._reply_label.pack(anchor="w", padx=4)

        self.new_comment = tk.Text(notes_tab, height=5, wrap=tk.WORD, font=("Arial", 9))
        self.new_comment.pack(fill=tk.X, pady=(2, 4), padx=4)

        action_bar = ttk.Frame(notes_tab)
        action_bar.pack(fill=tk.X, padx=4)

        self.btn_save = ttk.Button(action_bar, text="💾 Guardar Nota", command=self._save_comment)
        self.btn_save.pack(side=tk.LEFT, padx=2)
        self.btn_cancel = ttk.Button(action_bar, text="✖ Cancelar",
                                     command=self._cancel_edit_or_reply, state="disabled")
        self.btn_cancel.pack(side=tk.LEFT, padx=2)
        ttk.Button(action_bar, text="📤 Exportar notas", command=self._export_notes).pack(side=tk.RIGHT, padx=2)

        ttk.Label(
            notes_tab,
            text=f"Usuario: {self.current_user}  |  Firebase: {self.firebase_status}",
            style="Status.TLabel",
        ).pack(anchor="w", pady=(4, 0), padx=4)

    def _build_history_tab(self, notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Recientes")

        ttk.Label(tab, text="Archivos abiertos recientemente:").pack(anchor="w", padx=10, pady=5)

        frame = ttk.Frame(tab)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)

        self.history_list = tk.Listbox(frame, font=("Consolas", 9))
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.history_list.yview)
        self.history_list.configure(yscrollcommand=sb.set)
        self.history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.history_list.bind("<Double-Button-1>", lambda e: self._open_from_history())

    def _build_console_tab(self, notebook):
        """Pestaña que muestra el output de SOFA en tiempo real."""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="🖥 Consola")

        header = ttk.Frame(tab)
        header.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(header, text="Output de SOFA:").pack(side=tk.LEFT)
        ttk.Button(header, text="🗑 Limpiar", command=self._clear_console).pack(side=tk.RIGHT, padx=4)
        ttk.Button(header, text="💾 Guardar log", command=self._save_log).pack(side=tk.RIGHT, padx=4)

        text_frame = ttk.Frame(tab)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self.console_text = tk.Text(
            text_frame,
            font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white",
            state="disabled",
            wrap=tk.WORD,
        )
        console_sb = ttk.Scrollbar(text_frame, orient="vertical", command=self.console_text.yview)
        self.console_text.configure(yscrollcommand=console_sb.set)
        console_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.console_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.console_text.tag_configure("INFO",    foreground="#9cdcfe")
        self.console_text.tag_configure("WARNING", foreground="#dcdcaa")
        self.console_text.tag_configure("ERROR",   foreground="#f48771")
        self.console_text.tag_configure("OK",      foreground="#4ec9b0")
        self.console_text.tag_configure("DIM",     foreground="#555555")

        self._console_status = ttk.Label(tab, text="Sin simulación activa.", style="Status.TLabel")
        self._console_status.pack(anchor="w", padx=8, pady=(0, 4))

    # -----------------------------------------------------------------------
    # Pestaña Grupos colaborativos
    # -----------------------------------------------------------------------

    def _build_groups_tab(self, notebook):
        """Pestaña para gestionar grupos colaborativos."""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="👥 Grupos")

        # ---- Sección: Crear grupo ----
        create_frame = ttk.LabelFrame(tab, text="Crear nuevo grupo")
        create_frame.pack(fill=tk.X, padx=10, pady=(10, 4))

        row1 = ttk.Frame(create_frame)
        row1.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(row1, text="Nombre del grupo:").pack(side=tk.LEFT)
        self._new_group_name_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self._new_group_name_var, width=30).pack(side=tk.LEFT, padx=8)
        ttk.Button(row1, text="➕ Crear", command=self._create_group).pack(side=tk.LEFT)

        # ---- Sección: Mis grupos ----
        list_frame = ttk.LabelFrame(tab, text="Mis grupos")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        groups_list_frame = ttk.Frame(list_frame)
        groups_list_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self._groups_listbox = tk.Listbox(groups_list_frame, font=("Arial", 10), height=8)
        glist_sb = ttk.Scrollbar(groups_list_frame, orient="vertical",
                                  command=self._groups_listbox.yview)
        self._groups_listbox.configure(yscrollcommand=glist_sb.set)
        self._groups_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        glist_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._groups_listbox.bind("<<ListboxSelect>>", self._on_group_selected)

        btn_row = ttk.Frame(list_frame)
        btn_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(btn_row, text="✅ Usar este grupo",
                   command=self._activate_selected_group).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="🌐 Volver a Global",
                   command=self._activate_global).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="🔄 Actualizar",
                   command=lambda: threading.Thread(
                       target=self._refresh_my_groups, daemon=True).start()
                   ).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="🗑 Eliminar grupo",
                   command=self._delete_selected_group).pack(side=tk.RIGHT, padx=2)

        # ---- Sección: Gestionar miembros ----
        members_frame = ttk.LabelFrame(tab, text="Miembros del grupo seleccionado")
        members_frame.pack(fill=tk.X, padx=10, pady=4)

        self._members_text = tk.Text(
            members_frame, height=4, state="disabled",
            font=("Arial", 9), bg="#f9f9f9"
        )
        self._members_text.pack(fill=tk.X, padx=6, pady=(4, 2))

        member_row = ttk.Frame(members_frame)
        member_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(member_row, text="Agregar usuario:").pack(side=tk.LEFT)
        self._add_member_var = tk.StringVar()
        self._add_member_entry = ttk.Entry(member_row, textvariable=self._add_member_var, width=25)
        self._add_member_entry.pack(side=tk.LEFT, padx=6)
        self._add_member_entry.bind("<Return>", lambda e: self._add_member_to_selected())
        ttk.Button(member_row, text="➕ Agregar",
                   command=self._add_member_to_selected).pack(side=tk.LEFT)
        ttk.Button(member_row, text="➖ Remover",
                   command=self._remove_member_from_selected).pack(side=tk.LEFT, padx=4)

        # ---- Estado ----
        self._groups_status_label = ttk.Label(tab, text="", style="Status.TLabel")
        self._groups_status_label.pack(anchor="w", padx=10, pady=(2, 6))

        if not self.firebase:
            self._groups_status_label.config(
                text="⚠ Firebase no conectado — grupos no disponibles."
            )

    def _refresh_my_groups(self):
        """Obtiene los grupos del usuario desde Firebase y actualiza la lista (thread-safe)."""
        if not self.firebase:
            return
        try:
            groups = self.firebase.get_my_groups(self.current_user)
            self._my_groups = groups
            self.root.after(0, self._render_groups_list)
        except Exception as exc:
            self.root.after(
                0,
                lambda: self._groups_status_label.config(
                    text=f"Error al cargar grupos: {exc}"
                ),
            )

    def _render_groups_list(self):
        """Pinta la lista de grupos en el Listbox (debe llamarse desde el hilo UI)."""
        self._groups_listbox.delete(0, tk.END)
        if not self._my_groups:
            self._groups_listbox.insert(tk.END, "(sin grupos — crea uno arriba)")
            return

        for gid, gdata in self._my_groups.items():
            name    = gdata.get("name", gid)
            owner   = gdata.get("owner", "")
            members = gdata.get("members", {})
            n_members = len(members)
            marker = "👑 " if owner == self.current_user else "   "
            active = " ✅" if gid == self.active_group_id else ""
            self._groups_listbox.insert(
                tk.END, f"{marker}{name}  [{n_members} miembros]{active}"
            )

    def _selected_group_id(self) -> Optional[str]:
        """Devuelve el group_id del elemento seleccionado en la lista."""
        sel = self._groups_listbox.curselection()
        if not sel or not self._my_groups:
            return None
        idx = sel[0]
        keys = list(self._my_groups.keys())
        if idx >= len(keys):
            return None
        return keys[idx]

    def _on_group_selected(self, event=None):
        """Al seleccionar un grupo en la lista, muestra sus miembros."""
        gid = self._selected_group_id()
        if not gid:
            return
        gdata = self._my_groups.get(gid, {})
        members = list(gdata.get("members", {}).keys())
        owner = gdata.get("owner", "")

        self._members_text.configure(state="normal")
        self._members_text.delete("1.0", tk.END)
        for m in sorted(members):
            prefix = "👑 " if m == owner else "   "
            self._members_text.insert(tk.END, f"{prefix}{m}\n")
        self._members_text.configure(state="disabled")

    def _create_group(self):
        """Crea un nuevo grupo y refresca la lista."""
        if not self.firebase:
            messagebox.showerror("Sin conexión", "Firebase no está conectado.")
            return
        name = self._new_group_name_var.get().strip()
        if not name:
            messagebox.showwarning("Advertencia", "Escribe un nombre para el grupo.")
            return
        try:
            gid = self.firebase.create_group(name, self.current_user)
            self._new_group_name_var.set("")
            self._groups_status_label.config(
                text=f"✅ Grupo '{name}' creado (ID: {gid[:8]}…)"
            )
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo crear el grupo:\n{exc}")

    def _activate_selected_group(self):
        """Establece el grupo seleccionado como grupo activo para las notas."""
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo de la lista.")
            return
        gdata = self._my_groups.get(gid, {})
        name = gdata.get("name", gid)
        self.active_group_id   = gid
        self.active_group_name = name
        self._active_group_label.config(text=f"👥 {name}")
        self._groups_status_label.config(text=f"Grupo activo: {name}")
        self._render_groups_list()
        # Recargar notas del ejemplo actual con el nuevo grupo
        if self.current_example and self.firebase:
            self._reload_comments_for_current()

    def _activate_global(self):
        """Vuelve al modo de notas globales (sin grupo)."""
        self.active_group_id   = None
        self.active_group_name = "Global"
        self._active_group_label.config(text="🌐 Global")
        self._groups_status_label.config(text="Modo global activo.")
        self._render_groups_list()
        if self.current_example and self.firebase:
            self._reload_comments_for_current()

    def _delete_selected_group(self):
        """Elimina el grupo seleccionado (solo si el usuario es el creador)."""
        if not self.firebase:
            return
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo de la lista.")
            return
        gdata = self._my_groups.get(gid, {})
        if gdata.get("owner") != self.current_user:
            messagebox.showwarning(
                "Permiso denegado",
                "Solo el creador del grupo puede eliminarlo."
            )
            return
        name = gdata.get("name", gid)
        if not messagebox.askyesno(
            "Confirmar",
            f"¿Deseas eliminar el grupo '{name}'?\n"
            "Los comentarios del grupo NO se borrarán.",
        ):
            return
        try:
            self.firebase.delete_group(gid)
            if self.active_group_id == gid:
                self._activate_global()
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
            self._groups_status_label.config(text=f"Grupo '{name}' eliminado.")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo eliminar el grupo:\n{exc}")

    def _add_member_to_selected(self):
        """Agrega un nuevo miembro al grupo seleccionado."""
        if not self.firebase:
            return
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo de la lista.")
            return
        username = self._add_member_var.get().strip()
        if not username:
            messagebox.showwarning("Advertencia", "Escribe el nombre de usuario a agregar.")
            return
        gdata = self._my_groups.get(gid, {})
        if gdata.get("owner") != self.current_user:
            messagebox.showwarning(
                "Permiso denegado",
                "Solo el creador del grupo puede agregar miembros."
            )
            return
        try:
            self.firebase.add_member(gid, username)
            self._add_member_var.set("")
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
            self._groups_status_label.config(text=f"Usuario '{username}' agregado.")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo agregar el miembro:\n{exc}")

    def _remove_member_from_selected(self):
        """Remueve al usuario indicado en el campo de miembro."""
        if not self.firebase:
            return
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo de la lista.")
            return
        username = self._add_member_var.get().strip()
        if not username:
            messagebox.showwarning("Advertencia", "Escribe el nombre de usuario a remover.")
            return
        gdata = self._my_groups.get(gid, {})
        if gdata.get("owner") != self.current_user:
            messagebox.showwarning(
                "Permiso denegado",
                "Solo el creador del grupo puede remover miembros."
            )
            return
        if username == self.current_user:
            messagebox.showwarning("Advertencia", "No puedes removerte a ti mismo del grupo.")
            return
        try:
            self.firebase.remove_member(gid, username)
            self._add_member_var.set("")
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
            self._groups_status_label.config(text=f"Usuario '{username}' removido.")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo remover el miembro:\n{exc}")

    def _show_group_picker(self):
        """Despliega un mini-diálogo para seleccionar el grupo activo desde la pestaña Notas."""
        if not self.firebase:
            messagebox.showerror("Sin conexión", "Firebase no está conectado.")
            return
        if not self._my_groups:
            messagebox.showinfo("Sin grupos", "No perteneces a ningún grupo todavía.\n"
                                "Ve a la pestaña 👥 Grupos para crear o unirte a uno.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Seleccionar grupo")
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text="Selecciona el grupo activo:").pack(padx=16, pady=(12, 4))

        lb_frame = ttk.Frame(dlg)
        lb_frame.pack(fill=tk.BOTH, expand=True, padx=16)
        lb = tk.Listbox(lb_frame, font=("Arial", 10), height=8, selectmode="single")
        lb.pack(fill=tk.BOTH, expand=True)

        group_keys = []
        lb.insert(tk.END, "🌐 Global (notas compartidas con todos)")
        group_keys.append(None)
        for gid, gdata in self._my_groups.items():
            lb.insert(tk.END, f"👥 {gdata.get('name', gid)}")
            group_keys.append(gid)

        # Marcar el activo
        current_idx = 0
        if self.active_group_id in group_keys:
            current_idx = group_keys.index(self.active_group_id)
        lb.selection_set(current_idx)

        def _ok():
            sel = lb.curselection()
            if not sel:
                dlg.destroy()
                return
            idx = sel[0]
            chosen_id = group_keys[idx]
            if chosen_id is None:
                self._activate_global()
            else:
                gdata = self._my_groups.get(chosen_id, {})
                self.active_group_id   = chosen_id
                self.active_group_name = gdata.get("name", chosen_id)
                self._active_group_label.config(text=f"👥 {self.active_group_name}")
                if self.current_example:
                    self._reload_comments_for_current()
            dlg.destroy()

        ttk.Button(dlg, text="✅ Seleccionar", command=_ok).pack(pady=8)

    def _reload_comments_for_current(self):
        """Recarga los comentarios del ejemplo actual con el grupo activo."""
        if not self.current_example or not self.firebase:
            return

        def _fetch():
            gid = self.active_group_id
            comments = self.firebase.get_comments(self.current_example, gid)
            self.root.after(0, lambda: self._update_comments_display(comments))
            self.firebase.listen_updates(
                self.current_example,
                self._safe_update_comments,
                gid,
            )

        threading.Thread(target=_fetch, daemon=True).start()

    # -----------------------------------------------------------------------
    # Pestaña Configuración
    # -----------------------------------------------------------------------

    def _build_settings_tab(self, notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="⚙ Configuración")

        pad = {"padx": 10, "pady": 4}

        ttk.Label(tab, text="Ruta de runSofa.exe:").pack(anchor="w", **pad)
        exe_frame = ttk.Frame(tab)
        exe_frame.pack(fill=tk.X, padx=10)
        self._exe_var = tk.StringVar(value=self.sofa_executable)
        ttk.Entry(exe_frame, textvariable=self._exe_var, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(exe_frame, text="…", width=3,
                   command=lambda: self._browse_path(self._exe_var, "exe")).pack(side=tk.LEFT, padx=4)

        ttk.Label(tab, text="Carpeta de ejemplos:").pack(anchor="w", **pad)
        dir_frame = ttk.Frame(tab)
        dir_frame.pack(fill=tk.X, padx=10)
        self._dir_var = tk.StringVar(value=self.examples_dir)
        ttk.Entry(dir_frame, textvariable=self._dir_var, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(dir_frame, text="…", width=3,
                   command=lambda: self._browse_path(self._dir_var, "dir")).pack(side=tk.LEFT, padx=4)

        ttk.Separator(tab, orient="horizontal").pack(fill=tk.X, padx=10, pady=8)

        ttk.Label(tab, text="Nombre de usuario:").pack(anchor="w", **pad)
        self._user_var = tk.StringVar(value=self.current_user)
        ttk.Entry(tab, textvariable=self._user_var, width=40).pack(anchor="w", padx=10)
        ttk.Label(tab, text="Se usa para identificar tus comentarios en Firebase.",
                  style="Status.TLabel").pack(anchor="w", padx=10)

        ttk.Button(tab, text="Guardar y recargar", command=self._apply_settings).pack(anchor="w", padx=10, pady=10)

        self._settings_status = ttk.Label(tab, text="", style="Status.TLabel")
        self._settings_status.pack(anchor="w", padx=10)

    # -----------------------------------------------------------------------
    # Configuración de rutas
    # -----------------------------------------------------------------------

    def _browse_path(self, var: tk.StringVar, kind: str):
        if kind == "exe":
            path = filedialog.askopenfilename(
                title="Seleccionar runSofa.exe",
                filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")],
            )
        else:
            path = filedialog.askdirectory(title="Seleccionar carpeta de ejemplos")
        if path:
            var.set(path)

    def _load_config(self):
        defaults_needed = True
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.sofa_executable      = cfg.get("sofa_executable", "")
                self.examples_dir         = cfg.get("examples_dir", "")
                self.current_user         = cfg.get("current_user", os.getlogin())
                self.notification_enabled = cfg.get("notification_enabled", True)
                defaults_needed = False
            except Exception as exc:
                print(f"[Config] Error al leer config: {exc}")

        if defaults_needed:
            detected_exe, detected_examples = _find_sofa_installation()
            self.sofa_executable      = detected_exe
            self.examples_dir         = detected_examples
            self.current_user         = os.getlogin()
            self.notification_enabled = True

    def _save_config(self):
        cfg = {
            "sofa_executable":      self.sofa_executable,
            "examples_dir":         self.examples_dir,
            "current_user":         self.current_user,
            "notification_enabled": self._notif_enabled_var.get()
                                    if hasattr(self, "_notif_enabled_var") else self.notification_enabled,
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[Config] Error al guardar config: {exc}")

    def _on_close(self):
        self._save_config()
        self.root.destroy()

    def _apply_settings(self):
        self.sofa_executable = self._exe_var.get().strip()
        self.examples_dir    = self._dir_var.get().strip()
        self.current_user    = self._user_var.get().strip() or os.getlogin()
        self._load_examples()
        self._verify_installation(silent=True)
        self._save_config()
        self._settings_status.config(text="✅ Configuración guardada y lista actualizada.")

    # -----------------------------------------------------------------------
    # Notificaciones del sistema
    # -----------------------------------------------------------------------

    def _setup_notifications(self):
        self.notification_status = ttk.Label(self.root, text="🔔 0", style="Status.TLabel")
        self.notification_status.pack(side=tk.RIGHT, padx=10)

        menu = tk.Menu(self.root, tearoff=0)
        self._notif_enabled_var = tk.BooleanVar(value=True)
        menu.add_checkbutton(
            label="Activar notificaciones",
            variable=self._notif_enabled_var,
            command=self._toggle_notifications,
        )
        menu.add_command(label="Marcar todas como leídas", command=self._mark_all_read)

        self.notification_status.bind(
            "<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root)
        )

    def _on_new_comment_notification(self, example_name: str, user: str, text: str):
        if not self._notif_enabled_var.get():
            return
        self.unread_comments += 1
        self.root.after(0, self._update_notification_badge)

        preview = text[:100] + ("…" if len(text) > 100 else "")
        try:
            notification.notify(
                title=f"Nuevo comentario en {example_name}",
                message=f"{user}: {preview}",
                app_name="SOFA Manager",
                timeout=8,
            )
        except Exception:
            pass

    def _update_notification_badge(self):
        self.notification_status.config(
            text=f"🔔 {self.unread_comments}",
            foreground="red" if self.unread_comments > 0 else "gray",
        )

    def _toggle_notifications(self):
        estado = "activadas" if self._notif_enabled_var.get() else "desactivadas"
        messagebox.showinfo("Notificaciones", f"Notificaciones {estado}.")

    def _mark_all_read(self):
        self.unread_comments = 0
        self._update_notification_badge()

    # -----------------------------------------------------------------------
    # Gestión de ejemplos
    # -----------------------------------------------------------------------

    def _verify_installation(self, silent: bool = False):
        errors = []
        if not self.sofa_executable or not os.path.exists(self.sofa_executable):
            errors.append(
                "runSofa.exe no encontrado.\n"
                "Usa la pestaña ⚙ Configuración para indicar la ruta correcta."
            )
        if not self.examples_dir or not os.path.exists(self.examples_dir):
            errors.append(
                "Carpeta de ejemplos no encontrada.\n"
                "Usa la pestaña ⚙ Configuración para indicar la ruta correcta."
            )
        if errors and not silent:
            messagebox.showwarning("Configuración incompleta", "\n\n".join(errors))

    def _load_examples(self):
        self._all_examples = []
        self.example_list.delete(0, tk.END)

        if not self.examples_dir or not os.path.exists(self.examples_dir):
            return

        for dirpath, _, files in os.walk(self.examples_dir):
            for f in sorted(files):
                if f.lower().endswith((".scn", ".py", ".xml")):
                    rel = os.path.relpath(os.path.join(dirpath, f), self.examples_dir)
                    self._all_examples.append(rel)

        self._render_example_list(self._all_examples)

    def _render_example_list(self, items):
        self.example_list.delete(0, tk.END)
        for item in items:
            prefix = "⭐ " if item in self.favorites else "    "
            self.example_list.insert(tk.END, prefix + item)
        self._displayed_examples = list(items)

    def _get_real_name(self, display_text: str) -> str:
        return display_text.replace("⭐ ", "").strip()

    def _filter_examples(self):
        query = self._search_var.get().lower()
        filtered = []
        for item in self._all_examples:
            if self._show_only_favorites and item not in self.favorites:
                continue
            tags = self.tags_by_example.get(item, [])
            haystack = (item + " " + " ".join(tags)).lower()
            if query in haystack:
                filtered.append(item)
        self._render_example_list(filtered)

    def _toggle_favorites_filter(self):
        self._show_only_favorites = not self._show_only_favorites
        self._fav_filter_btn.config(
            text="⭐ Favoritos" if self._show_only_favorites else "☆ Favoritos"
        )
        self._filter_examples()

    def _toggle_current_favorite(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return
        if self.current_example in self.favorites:
            self.favorites.discard(self.current_example)
        else:
            self.favorites.add(self.current_example)
        self._save_tags_data()
        self._filter_examples()
        self._update_favorite_button()

    def _update_favorite_button(self):
        if not hasattr(self, "_fav_toggle_btn"):
            return
        if self.current_example in self.favorites:
            self._fav_toggle_btn.config(text="⭐ Quitar de favoritos")
        else:
            self._fav_toggle_btn.config(text="☆ Marcar como favorito")

    # -----------------------------------------------------------------------
    # Tags
    # -----------------------------------------------------------------------

    def _load_tags_data(self):
        if not os.path.exists(self.tags_file):
            return
        try:
            with open(self.tags_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.favorites       = set(data.get("favorites", []))
            self.tags_by_example = data.get("tags", {})
        except Exception as exc:
            print(f"[Tags] Error al cargar: {exc}")

    def _save_tags_data(self):
        try:
            with open(self.tags_file, "w", encoding="utf-8") as f:
                json.dump({
                    "favorites": sorted(self.favorites),
                    "tags": self.tags_by_example,
                }, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[Tags] Error al guardar: {exc}")

    def _add_tag_to_current(self):
        tag = self._new_tag_var.get().strip().lower()
        if not tag:
            return
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return
        tags = self.tags_by_example.setdefault(self.current_example, [])
        if tag not in tags:
            tags.append(tag)
            self._save_tags_data()
        self._new_tag_var.set("")
        self._render_tag_chips()

    def _remove_tag_from_current(self, tag: str):
        if not self.current_example:
            return
        tags = self.tags_by_example.get(self.current_example, [])
        if tag in tags:
            tags.remove(tag)
            self._save_tags_data()
        self._render_tag_chips()

    def _render_tag_chips(self):
        for w in self._tags_chip_frame.winfo_children():
            w.destroy()

        if not self.current_example:
            return

        tags = self.tags_by_example.get(self.current_example, [])
        for tag in tags:
            chip = tk.Frame(self._tags_chip_frame, bg="#2E75B6", padx=4, pady=1)
            chip.pack(side=tk.LEFT, padx=2)
            tk.Label(chip, text=tag, bg="#2E75B6", fg="white", font=("Arial", 8)).pack(side=tk.LEFT)
            tk.Label(
                chip, text=" ✕", bg="#2E75B6", fg="#cccccc", font=("Arial", 8, "bold"), cursor="hand2",
            ).pack(side=tk.LEFT)
            for child in chip.winfo_children():
                if child.cget("text") == " ✕":
                    child.bind("<Button-1>", lambda e, t=tag: self._remove_tag_from_current(t))

    def _browse_file(self):
        filepath = filedialog.askopenfilename(
            title="Seleccionar archivo SOFA",
            filetypes=[("Archivos SOFA", "*.scn *.py *.xml"), ("Todos los archivos", "*.*")],
        )
        if not filepath:
            return
        if self.examples_dir and filepath.startswith(self.examples_dir):
            rel = os.path.relpath(filepath, self.examples_dir)
        else:
            rel = filepath
        self.current_example = rel
        if rel not in self.example_list.get(0, tk.END):
            self.example_list.insert(tk.END, rel)
        self._open_example()
        self._save_to_history(filepath)

    def _open_example(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return

        if self.examples_dir:
            candidate = os.path.join(self.examples_dir, self.current_example)
        else:
            candidate = self.current_example

        if not os.path.exists(candidate):
            candidate = self.current_example
            if not os.path.exists(candidate):
                messagebox.showerror("Error", f"No se encontró el archivo:\n{self.current_example}")
                return

        if not self.sofa_executable or not os.path.exists(self.sofa_executable):
            messagebox.showerror(
                "SOFA no configurado",
                "No se encontró runSofa.exe.\n"
                "Ve a la pestaña ⚙ Configuración y selecciona el ejecutable.",
            )
            return

        try:
            env = self._build_sofa_env()
            proc = subprocess.Popen(
                [self.sofa_executable, "-l", "Sofa.GUI.Qt", "-g", "qt", candidate],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._save_to_history(candidate)
            self._console_log(f"\u25b6 Abriendo: {os.path.basename(candidate)}\n", tag="OK")
            self._console_status.config(
                text=f"Simulación activa: {os.path.basename(candidate)}  |  PID {proc.pid}"
            )
            threading.Thread(target=self._stream_sofa_output, args=(proc,), daemon=True).start()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo abrir el ejemplo:\n{exc}")

    def _build_sofa_env(self) -> dict:
        import copy
        env = copy.deepcopy(os.environ)

        exe_path    = Path(self.sofa_executable)
        library_bin = exe_path.parent
        library     = library_bin.parent
        conda_env   = library.parent

        extra_paths = [
            str(library_bin),
            str(library / "mingw-w64" / "bin"),
            str(conda_env / "bin"),
            str(conda_env / "Scripts"),
            str(conda_env),
        ]

        existing_path = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + existing_path

        sofa_root = str(library)
        env.setdefault("SOFA_ROOT", sofa_root)
        env.setdefault("SOFAPLUGIN_PATH", str(library / "lib" / "sofa" / "plugins"))

        return env

    # -----------------------------------------------------------------------
    # Historial
    # -----------------------------------------------------------------------

    def _save_to_history(self, filepath: str):
        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []
        if filepath in history:
            history.remove(filepath)
        history.insert(0, filepath)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(history[:30], f, indent=2, ensure_ascii=False)
        self._load_history()

    def _load_history(self):
        self.history_list.delete(0, tk.END)
        if not os.path.exists(self.history_file):
            return
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            for item in history:
                self.history_list.insert(tk.END, item)
        except Exception:
            pass

    def _open_from_history(self):
        sel = self.history_list.curselection()
        if not sel:
            return
        path = self.history_list.get(sel[0])
        if not os.path.exists(path):
            messagebox.showerror("Error", f"No se encontró el archivo:\n{path}")
            return
        if self.examples_dir and path.startswith(self.examples_dir):
            self.current_example = os.path.relpath(path, self.examples_dir)
        else:
            self.current_example = path
        self._open_example()

    def _clear_history(self):
        if messagebox.askyesno("Confirmar", "¿Deseas limpiar el historial?"):
            if os.path.exists(self.history_file):
                os.remove(self.history_file)
            self.history_list.delete(0, tk.END)

    # -----------------------------------------------------------------------
    # Comentarios / notas
    # -----------------------------------------------------------------------

    def _show_example_comments(self, event=None):
        sel = self.example_list.curselection()
        if not sel:
            return
        display_text = self.example_list.get(sel[0])
        example_name = self._get_real_name(display_text)
        self.current_example = example_name
        self._show_preview(example_name)
        self._update_favorite_button()
        self._render_tag_chips()
        self.unread_comments = 0
        self._update_notification_badge()
        self._cancel_edit_or_reply()

        if not self.firebase:
            self._clear_comments_frame()
            ttk.Label(self.comments_inner, text="⚠ Modo offline — sin conexión a Firebase.").pack(pady=10)
            return

        def _fetch():
            gid = self.active_group_id
            comments = self.firebase.get_comments(example_name, gid)
            self.root.after(0, lambda: self._update_comments_display(comments))
            self.firebase.listen_updates(example_name, self._safe_update_comments, gid)

        threading.Thread(target=_fetch, daemon=True).start()

    def _safe_update_comments(self, comments):
        self.root.after(0, lambda: self._update_comments_display(comments))

    def _clear_comments_frame(self):
        for widget in self.comments_inner.winfo_children():
            widget.destroy()

    # -----------------------------------------------------------------------
    # Avatares y colores por usuario
    # -----------------------------------------------------------------------

    _USER_COLOR_PALETTE = [
        "#E57373", "#F06292", "#BA68C8", "#9575CD",
        "#7986CB", "#64B5F6", "#4FC3F7", "#4DD0E1",
        "#4DB6AC", "#81C784", "#AED581", "#FFB74D",
        "#FF8A65", "#A1887F", "#90A4AE", "#F44336",
    ]

    def _color_for_user(self, user: str) -> str:
        if not user:
            return "#999999"
        h = sum(ord(c) for c in user) + len(user) * 17
        return self._USER_COLOR_PALETTE[h % len(self._USER_COLOR_PALETTE)]

    def _make_avatar(self, parent, user: str, bg: str, size: int = 28):
        initials = "".join(w[0] for w in user.split() if w).upper()[:2] or "?"
        color = self._color_for_user(user)

        canvas = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
        canvas.create_oval(1, 1, size - 1, size - 1, fill=color, outline="")
        canvas.create_text(
            size / 2, size / 2,
            text=initials,
            fill="white",
            font=("Arial", 9, "bold"),
        )
        return canvas

    def _update_comments_display(self, comments: dict):
        self._clear_comments_frame()

        # Indicador de contexto de grupo
        group_label_text = (
            f"👥 Grupo: {self.active_group_name}"
            if self.active_group_id
            else "🌐 Notas globales"
        )
        ttk.Label(
            self.comments_inner,
            text=group_label_text,
            style="Status.TLabel",
        ).pack(anchor="w", padx=6, pady=(2, 4))

        if not comments:
            ttk.Label(self.comments_inner, text="No hay notas para este ejemplo.").pack(pady=10)
            return

        self.current_comments = comments

        children_map = {}
        for cid, comment in comments.items():
            parent = comment.get("parent_id")
            children_map.setdefault(parent, []).append(cid)

        def display_thread(parent_id=None, level=0):
            if parent_id not in children_map:
                return
            for cid in sorted(
                children_map[parent_id],
                key=lambda x: comments[x].get("timestamp", 0),
                reverse=True,
            ):
                comment = comments[cid]
                user      = comment.get("user", "Anónimo")
                text      = comment.get("text", "")
                timestamp = comment.get("timestamp", "")

                if isinstance(timestamp, dict):
                    timestamp = "Recién guardado"
                elif isinstance(timestamp, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp / 1000).strftime("%d/%m/%Y %H:%M")

                bg = "#f0f4ff" if level > 0 else "#ffffff"
                user_color = self._color_for_user(user)

                outer = tk.Frame(self.comments_inner, background=bg)
                outer.pack(fill=tk.X, pady=3, padx=(12 * level, 6))

                side_bar = tk.Frame(outer, background=user_color, width=4)
                side_bar.pack(side=tk.LEFT, fill=tk.Y)

                c_frame = tk.Frame(outer, bd=1, relief="solid", background=bg)
                c_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                header = tk.Frame(c_frame, background=bg)
                header.pack(fill=tk.X, padx=6, pady=(4, 0))

                avatar = self._make_avatar(header, user, bg)
                avatar.pack(side=tk.LEFT, padx=(0, 6))

                tk.Label(
                    header,
                    text=user,
                    font=("Arial", 9, "bold"),
                    foreground=user_color,
                    background=bg,
                ).pack(side=tk.LEFT)
                tk.Label(
                    header,
                    text=f"🕒 {timestamp}",
                    font=("Arial", 8),
                    foreground="gray",
                    background=bg,
                ).pack(side=tk.LEFT, padx=8)

                tk.Label(
                    c_frame,
                    text=text,
                    wraplength=360,
                    justify="left",
                    anchor="w",
                    background=bg,
                    font=("Arial", 9),
                ).pack(fill=tk.X, padx=6, pady=2)

                btn_bar = tk.Frame(c_frame, background=bg)
                btn_bar.pack(fill=tk.X, padx=6, pady=(0, 4))

                if user == self.current_user:
                    ttk.Button(
                        btn_bar, text="✏ Editar",
                        command=lambda cid=cid: self._start_edit_comment(cid),
                    ).pack(side=tk.LEFT, padx=2)
                    ttk.Button(
                        btn_bar, text="🗑 Borrar",
                        command=lambda cid=cid: self._delete_comment(cid),
                    ).pack(side=tk.LEFT, padx=2)

                ttk.Button(
                    btn_bar, text="↩ Responder",
                    command=lambda cid=cid: self._start_reply_comment(cid),
                ).pack(side=tk.LEFT, padx=2)

                display_thread(cid, level + 1)

        display_thread()
        self.comments_canvas.yview_moveto(0)

    def _start_edit_comment(self, comment_id: str):
        if comment_id not in self.current_comments:
            return
        comment = self.current_comments[comment_id]
        if comment.get("user") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo puedes editar tus propios comentarios.")
            return
        self.editing_comment_id     = comment_id
        self.replying_to_comment_id = None
        self.new_comment.delete("1.0", tk.END)
        self.new_comment.insert(tk.END, comment.get("text", ""))
        self.btn_save.config(text="💾 Guardar Cambios")
        self.btn_cancel.config(state="normal")
        self._reply_label.config(text=f"✏ Editando comentario de {comment.get('user', '')}:")

    def _delete_comment(self, comment_id: str):
        if comment_id not in self.current_comments:
            return
        if self.current_comments[comment_id].get("user") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo puedes borrar tus propios comentarios.")
            return
        if not messagebox.askyesno("Confirmar", "¿Estás seguro de borrar este comentario?"):
            return
        try:
            self.firebase.delete_comment(
                self.current_example, comment_id, self.active_group_id
            )
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo borrar el comentario:\n{exc}")

    def _start_reply_comment(self, comment_id: str):
        if comment_id not in self.current_comments:
            return
        self.replying_to_comment_id = comment_id
        self.editing_comment_id     = None
        user = self.current_comments[comment_id].get("user", "")
        self.new_comment.delete("1.0", tk.END)
        self.new_comment.insert(tk.END, f"@{user} ")
        self.btn_save.config(text="↩ Guardar Respuesta")
        self.btn_cancel.config(state="normal")
        self._reply_label.config(text=f"↩ Respondiendo a {user}:")

    def _cancel_edit_or_reply(self):
        self.editing_comment_id     = None
        self.replying_to_comment_id = None
        self.new_comment.delete("1.0", tk.END)
        self.btn_save.config(text="💾 Guardar Nota")
        self.btn_cancel.config(state="disabled")
        self._reply_label.config(text="Añadir nueva nota:")

    def _save_comment(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return
        text = self.new_comment.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Advertencia", "La nota no puede estar vacía.")
            return
        if not self.firebase:
            messagebox.showerror("Sin conexión", "Firebase no está conectado.")
            return
        try:
            if self.editing_comment_id:
                self.firebase.update_comment(
                    self.current_example,
                    self.editing_comment_id,
                    text,
                    self.active_group_id,
                )
            else:
                self.firebase.save_comment(
                    self.current_example,
                    self.current_user,
                    text,
                    self.replying_to_comment_id,
                    self.active_group_id,
                )
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo guardar la nota:\n{exc}")
            return
        self._cancel_edit_or_reply()

    # -----------------------------------------------------------------------
    # Vista previa (imagen)
    # -----------------------------------------------------------------------

    def _previews_dir(self) -> str:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previews")
        os.makedirs(d, exist_ok=True)
        return d

    def _preview_image_path(self, example_name: str) -> str:
        base = os.path.splitext(os.path.basename(example_name))[0]
        for ext in (".png", ".jpg", ".jpeg"):
            p = os.path.join(self._previews_dir(), base + ext)
            if os.path.exists(p):
                return p
        return ""

    def _show_preview(self, example_name: str):
        self.preview_canvas.delete("all")
        self._preview_image_ref = None

        img_path = self._preview_image_path(example_name)
        if not img_path:
            self.preview_canvas.create_text(
                10, 10, anchor="nw",
                text=(
                    "Sin vista previa disponible.\n\n"
                    "Para agregar una imagen usa el bot\u00f3n\n"
                    "\"Asignar imagen a este ejemplo\"."
                ),
                fill="#666666",
                font=("Arial", 10),
            )
            return

        try:
            from PIL import Image, ImageTk
            img = Image.open(img_path)

            self.preview_canvas.update_idletasks()
            cw = self.preview_canvas.winfo_width()  or 400
            ch = self.preview_canvas.winfo_height() or 300
            img.thumbnail((cw, ch), Image.LANCZOS)

            photo = ImageTk.PhotoImage(img)
            self._preview_image_ref = photo

            x = cw // 2
            y = ch // 2
            self.preview_canvas.create_image(x, y, anchor="center", image=photo)
            self._preview_title.config(text=os.path.basename(img_path))

        except ImportError:
            self.preview_canvas.create_text(
                10, 10, anchor="nw",
                text="Instala Pillow para ver im\u00e1genes:\nconda install pillow",
                fill="#dcdcaa",
                font=("Consolas", 9),
            )
        except Exception as exc:
            self.preview_canvas.create_text(
                10, 10, anchor="nw",
                text=f"Error al cargar imagen:\n{exc}",
                fill="#f48771",
                font=("Consolas", 9),
            )

    def _assign_preview_image(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return

        src = filedialog.askopenfilename(
            title="Seleccionar imagen de preview",
            filetypes=[("Im\u00e1genes", "*.png *.jpg *.jpeg"), ("Todos", "*.*")],
        )
        if not src:
            return

        import shutil
        base = os.path.splitext(os.path.basename(self.current_example))[0]
        ext  = os.path.splitext(src)[1].lower()
        dest = os.path.join(self._previews_dir(), base + ext)
        try:
            shutil.copy2(src, dest)
            self._show_preview(self.current_example)
            messagebox.showinfo("Listo", f"Imagen asignada a {os.path.basename(self.current_example)}")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo copiar la imagen:\n{exc}")

    # -----------------------------------------------------------------------
    # Consola / log de ejecución
    # -----------------------------------------------------------------------

    def _stream_sofa_output(self, proc):
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                lu = line.upper()
                if "[ERROR]" in lu or "ERROR:" in lu:
                    tag = "ERROR"
                elif "[WARNING]" in lu:
                    tag = "WARNING"
                elif line.startswith("[#"):
                    tag = "DIM"
                else:
                    tag = "INFO"
                self.root.after(0, lambda l=line, t=tag: self._console_log(l + "\n", t))
        except Exception:
            pass
        finally:
            self.root.after(0, lambda: self._console_status.config(text="Simulación finalizada."))

    def _console_log(self, text: str, tag: str = "INFO"):
        self.console_text.configure(state="normal")
        self.console_text.insert(tk.END, text, tag)
        self.console_text.see(tk.END)
        self.console_text.configure(state="disabled")

    def _clear_console(self):
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", tk.END)
        self.console_text.configure(state="disabled")
        self._console_status.config(text="Sin simulación activa.")

    def _save_log(self):
        content = self.console_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Consola", "No hay nada que guardar.")
            return
        filepath = filedialog.asksaveasfilename(
            title="Guardar log",
            defaultextension=".txt",
            filetypes=[("Archivo de texto", "*.txt"), ("Todos", "*.*")],
            initialfile=f"sofa_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("Log guardado", f"Log guardado en:\n{filepath}")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo guardar:\n{exc}")

    # -----------------------------------------------------------------------
    # Exportar notas
    # -----------------------------------------------------------------------

    def _build_notes_markdown(self) -> str:
        comments = self.current_comments
        example  = self.current_example or "Sin ejemplo"
        group    = f"Grupo: {self.active_group_name}" if self.active_group_id else "Global"

        lines = [
            f"# Notas — {example}",
            "",
            f"*{group}  |  Exportado el {datetime.now().strftime('%d/%m/%Y %H:%M')}*",
            "",
        ]

        if not comments:
            lines.append("_No hay notas para este ejemplo._")
            return "\n".join(lines)

        children_map = {}
        for cid, comment in comments.items():
            parent = comment.get("parent_id")
            children_map.setdefault(parent, []).append(cid)

        def walk(parent_id=None, level=0):
            if parent_id not in children_map:
                return
            for cid in sorted(
                children_map[parent_id],
                key=lambda x: comments[x].get("timestamp", 0),
            ):
                c = comments[cid]
                user = c.get("user", "Anónimo")
                text = c.get("text", "")
                ts   = c.get("timestamp", "")
                if isinstance(ts, dict):
                    ts = "reciente"
                elif isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(ts / 1000).strftime("%d/%m/%Y %H:%M")

                indent = "  " * level
                bullet = "- " if level == 0 else "- ↳ "
                lines.append(f"{indent}{bullet}**{user}** _({ts})_: {text}")
                walk(cid, level + 1)

        walk()
        return "\n".join(lines)

    def _export_notes(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return

        fmt = messagebox.askquestion(
            "Formato de exportación",
            "¿Exportar como PDF?\n\nSí = PDF\nNo = Markdown (.md)",
        )

        base_name = os.path.splitext(os.path.basename(self.current_example))[0]
        markdown_content = self._build_notes_markdown()

        if fmt == "yes":
            self._export_notes_pdf(base_name, markdown_content)
        else:
            self._export_notes_markdown(base_name, markdown_content)

    def _export_notes_markdown(self, base_name: str, content: str):
        filepath = filedialog.asksaveasfilename(
            title="Guardar notas como Markdown",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Todos", "*.*")],
            initialfile=f"notas_{base_name}.md",
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("Exportado", f"Notas guardadas en:\n{filepath}")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo exportar:\n{exc}")

    def _export_notes_pdf(self, base_name: str, markdown_content: str):
        try:
            from fpdf import FPDF
        except ImportError:
            messagebox.showerror(
                "Falta una librería",
                "Para exportar a PDF se necesita fpdf2.\n\n"
                "Instálala con:\nconda activate sofa\npip install fpdf2",
            )
            return

        filepath = filedialog.asksaveasfilename(
            title="Guardar notas como PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
            initialfile=f"notas_{base_name}.pdf",
        )
        if not filepath:
            return

        try:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)

            for raw_line in markdown_content.split("\n"):
                line = raw_line.strip()

                if line.startswith("# "):
                    pdf.set_font("Helvetica", "B", 16)
                    pdf.multi_cell(0, 9, line[2:].encode("latin-1", "replace").decode("latin-1"))
                    pdf.ln(2)
                elif line.startswith("*") and line.endswith("*") and not line.startswith("- "):
                    pdf.set_font("Helvetica", "I", 9)
                    pdf.set_text_color(120, 120, 120)
                    pdf.multi_cell(0, 6, line.strip("*").encode("latin-1", "replace").decode("latin-1"))
                    pdf.set_text_color(0, 0, 0)
                    pdf.ln(2)
                elif line.startswith("- "):
                    pdf.set_font("Helvetica", "", 10)
                    clean = line.replace("**", "").replace("_", "")
                    indent = 8 if "\u21b3" in line else 0
                    pdf.set_x(10 + indent)
                    pdf.multi_cell(0, 6, clean.encode("latin-1", "replace").decode("latin-1"))
                elif line:
                    pdf.set_font("Helvetica", "", 10)
                    pdf.multi_cell(0, 6, line.encode("latin-1", "replace").decode("latin-1"))
                else:
                    pdf.ln(2)

            pdf.output(filepath)
            messagebox.showinfo("Exportado", f"Notas guardadas en:\n{filepath}")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo generar el PDF:\n{exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    SOFAInterface(root)
    root.mainloop()


if __name__ == "__main__":
    main()
