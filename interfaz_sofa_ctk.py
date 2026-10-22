"""
interfaz_sofa_ctk.py  –  SOFA Manager v4.0
Interfaz moderna con CustomTkinter (dark/light mode).
Requiere: firebase_handler.py, firebase-key.json y .env en el mismo directorio.
Instalar: pip install customtkinter pillow plyer firebase-admin python-dotenv
"""

import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

import customtkinter as ctk
from tkinter import filedialog, messagebox
from plyer import notification

from firebase_handler import FirebaseManager

# ── Tema global ──────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")          # "dark" | "light" | "system"
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# Detección automática de la instalación de SOFA
# ---------------------------------------------------------------------------

def _find_sofa_installation() -> tuple:
    candidate_roots = []
    for base in [
        Path.home() / "anaconda3",
        Path.home() / "miniconda3",
        Path("C:/ProgramData/Anaconda3"),
        Path("C:/ProgramData/miniconda3"),
    ]:
        envs = base / "envs"
        if envs.exists():
            for env in envs.iterdir():
                candidate_roots.append(env / "Library")
        candidate_roots.append(base / "Library")
    for pf in ["C:/Program Files/SOFA", "C:/Program Files (x86)/SOFA"]:
        p = Path(pf)
        if p.exists():
            candidate_roots.append(p)

    exe_path = examples_path = ""
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


# ── Colores de usuario ────────────────────────────────────────────────────────
_PALETTE = [
    "#E57373","#F06292","#BA68C8","#9575CD","#7986CB","#64B5F6",
    "#4FC3F7","#4DD0E1","#4DB6AC","#81C784","#AED581","#FFB74D",
    "#FF8A65","#A1887F","#90A4AE","#F44336",
]

def _color_for_user(user: str) -> str:
    if not user:
        return "#888888"
    h = sum(ord(c) for c in user) + len(user) * 17
    return _PALETTE[h % len(_PALETTE)]


# ===========================================================================
# Clase principal
# ===========================================================================

class SOFAInterface:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("SOFA Manager v4.0")
        self.root.geometry("1200x820")
        self.root.minsize(960, 680)

        # Archivos locales
        base = Path(__file__).parent
        self.config_file  = str(base / "sofa_config.json")
        self.history_file = str(base / "sofa_history.json")
        self.tags_file    = str(base / "sofa_tags.json")

        self.favorites:        set  = set()
        self.tags_by_example:  dict = {}
        self._show_only_favorites   = False

        self._load_config()
        self._load_tags_data()

        # Estado interno
        self.current_example        = None
        self.unread_comments        = 0
        self.editing_comment_id     = None
        self.replying_to_comment_id = None
        self.current_comments:  dict = {}
        self.active_group_id: Optional[str] = None
        self.active_group_name: str = "Global"
        self._my_groups: Dict[str, dict] = {}
        self._displayed_examples: list = []
        self._all_examples: list = []

        # Firebase
        try:
            self.firebase = FirebaseManager()
            self.firebase.set_notification_callback(self._on_new_comment_notification)
            self.firebase_status = "✅ Conectado"
        except Exception as exc:
            print(f"[Firebase] Error al conectar: {exc}")
            self.firebase = None
            self.firebase_status = "❌ Desconectado"

        self._build_ui()
        self._setup_notifications()
        self._load_history()
        self._load_examples()
        self._verify_installation()

        if self.firebase:
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================================
    # UI principal
    # =========================================================================

    def _build_ui(self):
        # ── Barra lateral izquierda ──────────────────────────────────────────
        self.sidebar = ctk.CTkFrame(self.root, width=220, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(
            self.sidebar, text="SOFA Manager",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(padx=16, pady=(24, 4))

        ctk.CTkLabel(
            self.sidebar, text="v4.0",
            font=ctk.CTkFont(size=12), text_color="gray",
        ).pack()

        ctk.CTkLabel(self.sidebar, text="").pack(pady=8)  # spacer

        # Botones de navegación
        self._nav_buttons = {}
        nav_items = [
            ("📁  Ejemplos",    "examples"),
            ("🕐  Recientes",   "history"),
            ("🖥  Consola",     "console"),
            ("👥  Grupos",      "groups"),
            ("⚙   Configuración","settings"),
        ]
        for label, key in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=label, anchor="w",
                fg_color="transparent", hover_color=("gray75","gray25"),
                font=ctk.CTkFont(size=13),
                command=lambda k=key: self._switch_tab(k),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_buttons[key] = btn

        # Separador y acciones rápidas
        ctk.CTkFrame(self.sidebar, height=1, fg_color="gray40").pack(fill="x", padx=12, pady=12)

        ctk.CTkButton(
            self.sidebar, text="▶  Abrir ejemplo",
            font=ctk.CTkFont(size=12),
            command=self._open_example,
        ).pack(fill="x", padx=12, pady=3)

        ctk.CTkButton(
            self.sidebar, text="🔍  Buscar archivo…",
            font=ctk.CTkFont(size=12),
            fg_color=("gray70","gray30"),
            command=self._browse_file,
        ).pack(fill="x", padx=12, pady=3)

        ctk.CTkButton(
            self.sidebar, text="🔄  Actualizar lista",
            font=ctk.CTkFont(size=12),
            fg_color=("gray70","gray30"),
            command=self._load_examples,
        ).pack(fill="x", padx=12, pady=3)

        # Indicador Firebase
        ctk.CTkFrame(self.sidebar, height=1, fg_color="gray40").pack(fill="x", padx=12, pady=12)
        self._fb_label = ctk.CTkLabel(
            self.sidebar,
            text=self.firebase_status,
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._fb_label.pack(padx=12, pady=2)

        # Indicador usuario
        self._user_sidebar_label = ctk.CTkLabel(
            self.sidebar,
            text=f"👤 {self.current_user}",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._user_sidebar_label.pack(padx=12, pady=2)

        # Apariencia
        ctk.CTkFrame(self.sidebar, height=1, fg_color="gray40").pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(self.sidebar, text="Tema:", font=ctk.CTkFont(size=11), text_color="gray").pack(padx=12)
        self._theme_switch = ctk.CTkOptionMenu(
            self.sidebar, values=["Dark", "Light", "System"],
            command=lambda v: ctk.set_appearance_mode(v.lower()),
            width=160,
        )
        self._theme_switch.pack(padx=12, pady=4)

        # ── Panel principal derecho ──────────────────────────────────────────
        self.main_area = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        self.main_area.pack(side="left", fill="both", expand=True, padx=0)

        # Construir todas las pestañas (solo una visible a la vez)
        self._tabs: Dict[str, ctk.CTkFrame] = {}
        self._build_examples_tab()
        self._build_history_tab()
        self._build_console_tab()
        self._build_groups_tab()
        self._build_settings_tab()

        self._switch_tab("examples")

    def _switch_tab(self, key: str):
        for k, frame in self._tabs.items():
            frame.pack_forget()
        self._tabs[key].pack(fill="both", expand=True)
        # Resaltar botón activo
        for k, btn in self._nav_buttons.items():
            btn.configure(
                fg_color=("gray75","gray30") if k == key else "transparent"
            )

    # =========================================================================
    # Pestaña: Ejemplos
    # =========================================================================

    def _build_examples_tab(self):
        tab = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self._tabs["examples"] = tab

        # Título
        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(header, text="Ejemplos SOFA",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")

        # ── División: lista + detalle ────────────────────────────────────────
        body = ctk.CTkFrame(tab, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        # Panel izquierdo
        left = ctk.CTkFrame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(left, text="Buscar:", font=ctk.CTkFont(size=12)).pack(
            anchor="w", padx=12, pady=(12, 4))

        search_row = ctk.CTkFrame(left, fg_color="transparent")
        search_row.pack(fill="x", padx=12, pady=(0, 6))
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_examples())
        ctk.CTkEntry(search_row, textvariable=self._search_var,
                     placeholder_text="nombre o tag…").pack(side="left", fill="x", expand=True)
        self._fav_filter_btn = ctk.CTkButton(
            search_row, text="☆ Favs", width=70,
            fg_color=("gray70","gray30"),
            command=self._toggle_favorites_filter,
        )
        self._fav_filter_btn.pack(side="left", padx=(6, 0))

        # Lista de ejemplos (CTkScrollableFrame con Labels clicables)
        self._examples_scroll = ctk.CTkScrollableFrame(left, label_text="")
        self._examples_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._fav_toggle_btn = ctk.CTkButton(
            left, text="☆ Marcar favorito",
            fg_color=("gray70","gray30"), font=ctk.CTkFont(size=12),
            command=self._toggle_current_favorite,
        )
        self._fav_toggle_btn.pack(fill="x", padx=12, pady=(0, 10))

        # Panel derecho (sub-tabs)
        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew")

        right_tabs = ctk.CTkTabview(right)
        right_tabs.pack(fill="both", expand=True, padx=8, pady=8)
        right_tabs.add("📄 Vista previa")
        right_tabs.add("🗒 Notas")

        # ── Vista previa ─────────────────────────────────────────────────────
        pv = right_tabs.tab("📄 Vista previa")

        pv_header = ctk.CTkFrame(pv, fg_color="transparent")
        pv_header.pack(fill="x", pady=(8, 4))
        self._preview_title = ctk.CTkLabel(
            pv_header, text="Selecciona un ejemplo.",
            font=ctk.CTkFont(size=12), text_color="gray",
        )
        self._preview_title.pack(side="left", padx=8)
        ctk.CTkButton(pv_header, text="▶ Abrir", width=90,
                      command=self._open_example).pack(side="right", padx=8)

        # Tags bar
        tags_row = ctk.CTkFrame(pv, fg_color="transparent")
        tags_row.pack(fill="x", padx=8, pady=(0, 6))
        self._tags_chip_frame = ctk.CTkFrame(tags_row, fg_color="transparent")
        self._tags_chip_frame.pack(side="left", fill="x", expand=True)
        self._new_tag_var = ctk.StringVar()
        tag_entry = ctk.CTkEntry(tags_row, textvariable=self._new_tag_var,
                                 placeholder_text="nuevo tag", width=120)
        tag_entry.pack(side="right")
        tag_entry.bind("<Return>", lambda e: self._add_tag_to_current())
        ctk.CTkButton(tags_row, text="+ Tag", width=60,
                      command=self._add_tag_to_current).pack(side="right", padx=4)

        # Canvas de imagen (dark bg)
        import tkinter as tk
        self._preview_canvas_frame = ctk.CTkFrame(pv, fg_color="#111111")
        self._preview_canvas_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.preview_canvas = tk.Canvas(
            self._preview_canvas_frame, bg="#111111", highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True)
        self._preview_image_ref = None

        self.preview_canvas.create_text(
            10, 10, anchor="nw",
            text="Selecciona un ejemplo para ver su vista previa.",
            fill="#555555", font=("Arial", 10),
        )

        ctk.CTkButton(
            pv, text="📂 Asignar imagen a este ejemplo",
            fg_color=("gray70","gray30"), font=ctk.CTkFont(size=12),
            command=self._assign_preview_image,
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # ── Notas ────────────────────────────────────────────────────────────
        nt = right_tabs.tab("🗒 Notas")

        group_row = ctk.CTkFrame(nt, fg_color="transparent")
        group_row.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(group_row, text="Grupo activo:",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self._active_group_label = ctk.CTkLabel(
            group_row, text="🌐 Global",
            font=ctk.CTkFont(size=12), text_color="gray",
        )
        self._active_group_label.pack(side="left", padx=8)
        ctk.CTkButton(
            group_row, text="👥 Cambiar", width=100,
            fg_color=("gray70","gray30"),
            command=self._show_group_picker,
        ).pack(side="left")

        ctk.CTkLabel(nt, text="Notas compartidas:",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=8, pady=(4, 2))

        self.comments_scroll = ctk.CTkScrollableFrame(nt, height=220)
        self.comments_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        ctk.CTkFrame(nt, height=1, fg_color="gray40").pack(fill="x", padx=8, pady=4)

        self._reply_label = ctk.CTkLabel(nt, text="Añadir nueva nota:",
                                         font=ctk.CTkFont(size=12))
        self._reply_label.pack(anchor="w", padx=8)

        self.new_comment = ctk.CTkTextbox(nt, height=90, wrap="word",
                                          font=ctk.CTkFont(size=12))
        self.new_comment.pack(fill="x", padx=8, pady=(4, 4))

        action_row = ctk.CTkFrame(nt, fg_color="transparent")
        action_row.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_save = ctk.CTkButton(action_row, text="💾 Guardar nota",
                                      command=self._save_comment)
        self.btn_save.pack(side="left", padx=2)
        self.btn_cancel = ctk.CTkButton(
            action_row, text="✖ Cancelar",
            fg_color=("gray70","gray30"),
            state="disabled",
            command=self._cancel_edit_or_reply,
        )
        self.btn_cancel.pack(side="left", padx=2)
        ctk.CTkButton(
            action_row, text="📤 Exportar",
            fg_color=("gray70","gray30"),
            command=self._export_notes,
        ).pack(side="right", padx=2)

        ctk.CTkLabel(
            nt,
            text=f"Usuario: {self.current_user}  |  Firebase: {self.firebase_status}",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).pack(anchor="w", padx=8, pady=(0, 8))

    # =========================================================================
    # Pestaña: Recientes
    # =========================================================================

    def _build_history_tab(self):
        tab = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self._tabs["history"] = tab

        ctk.CTkLabel(tab, text="Archivos recientes",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 8))

        self._history_scroll = ctk.CTkScrollableFrame(tab, label_text="")
        self._history_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        ctk.CTkButton(
            tab, text="🗑  Limpiar historial",
            fg_color=("gray70","gray30"),
            command=self._clear_history,
        ).pack(anchor="e", padx=20, pady=(0, 16))

    # =========================================================================
    # Pestaña: Consola
    # =========================================================================

    def _build_console_tab(self):
        import tkinter as tk
        tab = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self._tabs["console"] = tab

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(header, text="Consola SOFA",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="🗑 Limpiar", width=90,
                      fg_color=("gray70","gray30"),
                      command=self._clear_console).pack(side="right", padx=4)
        ctk.CTkButton(header, text="💾 Guardar log", width=110,
                      fg_color=("gray70","gray30"),
                      command=self._save_log).pack(side="right", padx=4)

        console_frame = ctk.CTkFrame(tab, fg_color="#0d0d0d")
        console_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        self.console_text = tk.Text(
            console_frame,
            font=("Consolas", 10),
            bg="#0d0d0d", fg="#d4d4d4",
            insertbackground="white",
            state="disabled",
            wrap="word",
            padx=10, pady=8,
            relief="flat",
            borderwidth=0,
        )
        sb = tk.Scrollbar(console_frame, orient="vertical",
                          command=self.console_text.yview)
        self.console_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.console_text.pack(side="left", fill="both", expand=True)

        self.console_text.tag_configure("INFO",    foreground="#9cdcfe")
        self.console_text.tag_configure("WARNING", foreground="#dcdcaa")
        self.console_text.tag_configure("ERROR",   foreground="#f48771")
        self.console_text.tag_configure("OK",      foreground="#4ec9b0")
        self.console_text.tag_configure("DIM",     foreground="#555555")

        self._console_status = ctk.CTkLabel(
            tab, text="Sin simulación activa.",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._console_status.pack(anchor="w", padx=20, pady=(0, 12))

    # =========================================================================
    # Pestaña: Grupos
    # =========================================================================

    def _build_groups_tab(self):
        tab = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self._tabs["groups"] = tab

        ctk.CTkLabel(tab, text="Grupos colaborativos",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 12))

        # ── Crear grupo ──────────────────────────────────────────────────────
        create_card = ctk.CTkFrame(tab)
        create_card.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(create_card, text="Crear nuevo grupo",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=14, pady=(10, 6))

        row1 = ctk.CTkFrame(create_card, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(0, 10))
        self._new_group_name_var = ctk.StringVar()
        ctk.CTkEntry(row1, textvariable=self._new_group_name_var,
                     placeholder_text="Nombre del grupo…", width=280).pack(side="left")
        ctk.CTkButton(row1, text="➕ Crear", width=100,
                      command=self._create_group).pack(side="left", padx=10)

        # ── División grupos + miembros ────────────────────────────────────────
        mid = ctk.CTkFrame(tab, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)

        # Lista de grupos
        groups_card = ctk.CTkFrame(mid)
        groups_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(groups_card, text="Mis grupos",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=14, pady=(10, 6))

        self._groups_scroll = ctk.CTkScrollableFrame(groups_card, height=220)
        self._groups_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        grp_btns = ctk.CTkFrame(groups_card, fg_color="transparent")
        grp_btns.pack(fill="x", padx=8, pady=(0, 10))
        ctk.CTkButton(grp_btns, text="✅ Usar grupo", width=110,
                      command=self._activate_selected_group).pack(side="left", padx=2)
        ctk.CTkButton(grp_btns, text="🌐 Global", width=90,
                      fg_color=("gray70","gray30"),
                      command=self._activate_global).pack(side="left", padx=2)
        ctk.CTkButton(grp_btns, text="🔄", width=40,
                      fg_color=("gray70","gray30"),
                      command=lambda: threading.Thread(
                          target=self._refresh_my_groups, daemon=True).start()
                      ).pack(side="left", padx=2)
        ctk.CTkButton(grp_btns, text="🗑 Eliminar", width=100,
                      fg_color="#b71c1c",
                      command=self._delete_selected_group).pack(side="right", padx=2)

        # Panel miembros
        members_card = ctk.CTkFrame(mid)
        members_card.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(members_card, text="Miembros",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=14, pady=(10, 6))

        self._members_scroll = ctk.CTkScrollableFrame(members_card, height=180)
        self._members_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        mem_row = ctk.CTkFrame(members_card, fg_color="transparent")
        mem_row.pack(fill="x", padx=8, pady=(0, 10))
        self._add_member_var = ctk.StringVar()
        mem_entry = ctk.CTkEntry(mem_row, textvariable=self._add_member_var,
                                 placeholder_text="nombre de usuario", width=180)
        mem_entry.pack(side="left")
        mem_entry.bind("<Return>", lambda e: self._add_member_to_selected())
        ctk.CTkButton(mem_row, text="➕", width=40,
                      command=self._add_member_to_selected).pack(side="left", padx=4)
        ctk.CTkButton(mem_row, text="➖", width=40,
                      fg_color=("gray70","gray30"),
                      command=self._remove_member_from_selected).pack(side="left")

        self._groups_status_label = ctk.CTkLabel(
            tab, text="" if self.firebase else "⚠ Firebase no conectado — grupos no disponibles.",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._groups_status_label.pack(anchor="w", padx=20, pady=(0, 8))

        # Variable para saber qué grupo está seleccionado en la UI
        self._selected_group_ui_id: Optional[str] = None

    # =========================================================================
    # Pestaña: Configuración
    # =========================================================================

    def _build_settings_tab(self):
        tab = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self._tabs["settings"] = tab

        ctk.CTkLabel(tab, text="Configuración",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 12))

        card = ctk.CTkFrame(tab)
        card.pack(fill="x", padx=20, pady=(0, 12))

        # runSofa
        ctk.CTkLabel(card, text="Ruta de runSofa.exe:",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(12, 2))
        exe_row = ctk.CTkFrame(card, fg_color="transparent")
        exe_row.pack(fill="x", padx=14, pady=(0, 8))
        self._exe_var = ctk.StringVar(value=self.sofa_executable)
        ctk.CTkEntry(exe_row, textvariable=self._exe_var).pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(exe_row, text="…", width=36,
                      command=lambda: self._browse_path(self._exe_var, "exe")).pack(
            side="left", padx=6)

        # Carpeta ejemplos
        ctk.CTkLabel(card, text="Carpeta de ejemplos:",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(0, 2))
        dir_row = ctk.CTkFrame(card, fg_color="transparent")
        dir_row.pack(fill="x", padx=14, pady=(0, 8))
        self._dir_var = ctk.StringVar(value=self.examples_dir)
        ctk.CTkEntry(dir_row, textvariable=self._dir_var).pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(dir_row, text="…", width=36,
                      command=lambda: self._browse_path(self._dir_var, "dir")).pack(
            side="left", padx=6)

        ctk.CTkFrame(card, height=1, fg_color="gray40").pack(fill="x", padx=14, pady=8)

        # Usuario
        ctk.CTkLabel(card, text="Nombre de usuario:",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(0, 2))
        self._user_var = ctk.StringVar(value=self.current_user)
        ctk.CTkEntry(card, textvariable=self._user_var, width=260).pack(
            anchor="w", padx=14, pady=(0, 4))
        ctk.CTkLabel(card, text="Se usa para identificar tus comentarios en Firebase.",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(
            anchor="w", padx=14, pady=(0, 12))

        ctk.CTkButton(card, text="💾 Guardar y recargar",
                      command=self._apply_settings).pack(anchor="w", padx=14, pady=(0, 12))

        self._settings_status = ctk.CTkLabel(
            tab, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self._settings_status.pack(anchor="w", padx=20, pady=(0, 8))

    # =========================================================================
    # Renderizado de listas (dinámico)
    # =========================================================================

    def _render_example_list(self, items):
        for w in self._examples_scroll.winfo_children():
            w.destroy()
        self._displayed_examples = list(items)

        for item in items:
            is_fav = item in self.favorites
            star = "⭐" if is_fav else "  "
            row = ctk.CTkFrame(self._examples_scroll, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkButton(
                row,
                text=f"{star} {item}",
                anchor="w",
                fg_color="transparent",
                hover_color=("gray75","gray25"),
                font=ctk.CTkFont(size=11),
                command=lambda i=item: self._select_example(i),
            ).pack(fill="x")

    def _select_example(self, example_name: str):
        self.current_example = example_name
        self._show_preview(example_name)
        self._update_favorite_button()
        self._render_tag_chips()
        self.unread_comments = 0
        self._update_notification_badge()
        self._cancel_edit_or_reply()

        if not self.firebase:
            self._clear_comments_frame()
            ctk.CTkLabel(self.comments_scroll,
                         text="⚠ Modo offline — sin conexión a Firebase.").pack(pady=10)
            return

        def _fetch():
            gid = self.active_group_id
            comments = self.firebase.get_comments(example_name, gid)
            self.root.after(0, lambda: self._update_comments_display(comments))
            self.firebase.listen_updates(example_name, self._safe_update_comments, gid)

        threading.Thread(target=_fetch, daemon=True).start()

    def _load_history(self):
        for w in self._history_scroll.winfo_children():
            w.destroy()
        if not os.path.exists(self.history_file):
            return
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            for path in history:
                ctk.CTkButton(
                    self._history_scroll,
                    text=path, anchor="w",
                    fg_color="transparent",
                    hover_color=("gray75","gray25"),
                    font=ctk.CTkFont(size=11),
                    command=lambda p=path: self._open_from_history_path(p),
                ).pack(fill="x", pady=1)
        except Exception:
            pass

    def _render_groups_list(self):
        for w in self._groups_scroll.winfo_children():
            w.destroy()
        self._selected_group_ui_id = None

        if not self._my_groups:
            ctk.CTkLabel(self._groups_scroll,
                         text="(sin grupos — crea uno arriba)",
                         text_color="gray").pack(pady=8)
            return

        for gid, gdata in self._my_groups.items():
            name = gdata.get("name", gid)
            owner = gdata.get("owner", "")
            n_members = len(gdata.get("members", {}))
            is_owner = owner == self.current_user
            is_active = gid == self.active_group_id

            crown = "👑 " if is_owner else ""
            active_mark = "  ✅" if is_active else ""
            label = f"{crown}{name}  [{n_members} miembro{'s' if n_members != 1 else ''}]{active_mark}"

            btn = ctk.CTkButton(
                self._groups_scroll,
                text=label, anchor="w",
                fg_color=("gray70","gray30") if is_active else "transparent",
                hover_color=("gray75","gray25"),
                font=ctk.CTkFont(size=12),
                command=lambda g=gid: self._on_group_row_click(g),
            )
            btn.pack(fill="x", pady=2)

    def _on_group_row_click(self, gid: str):
        self._selected_group_ui_id = gid
        # Mostrar miembros
        for w in self._members_scroll.winfo_children():
            w.destroy()
        gdata = self._my_groups.get(gid, {})
        owner = gdata.get("owner", "")
        for m in sorted(gdata.get("members", {}).keys()):
            crown = "👑 " if m == owner else "   "
            ctk.CTkLabel(
                self._members_scroll,
                text=f"{crown}{m}",
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", pady=2)

    # =========================================================================
    # Notificaciones (badge en sidebar)
    # =========================================================================

    def _setup_notifications(self):
        self._notif_enabled = True
        self._notif_badge = ctk.CTkLabel(
            self.sidebar,
            text="🔔 0",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._notif_badge.pack(padx=12, pady=2)
        self._notif_badge.bind("<Button-1>", lambda e: self._mark_all_read())

    def _on_new_comment_notification(self, example_name: str, user: str, text: str):
        if not self._notif_enabled:
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
        color = "red" if self.unread_comments > 0 else "gray"
        self._notif_badge.configure(
            text=f"🔔 {self.unread_comments}", text_color=color)

    def _mark_all_read(self):
        self.unread_comments = 0
        self._update_notification_badge()

    # =========================================================================
    # Ejemplos: carga, filtrado, favoritos, tags
    # =========================================================================

    def _load_examples(self):
        self._all_examples = []
        if not self.examples_dir or not os.path.exists(self.examples_dir):
            self._render_example_list([])
            return
        for dirpath, _, files in os.walk(self.examples_dir):
            for f in sorted(files):
                if f.lower().endswith((".scn", ".py", ".xml")):
                    rel = os.path.relpath(os.path.join(dirpath, f), self.examples_dir)
                    self._all_examples.append(rel)
        self._render_example_list(self._all_examples)

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
        self._fav_filter_btn.configure(
            text="⭐ Favs" if self._show_only_favorites else "☆ Favs")
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
        if not self.current_example:
            return
        if self.current_example in self.favorites:
            self._fav_toggle_btn.configure(text="⭐ Quitar de favoritos")
        else:
            self._fav_toggle_btn.configure(text="☆ Marcar favorito")

    def _load_tags_data(self):
        if not os.path.exists(self.tags_file):
            return
        try:
            with open(self.tags_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.favorites = set(data.get("favorites", []))
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
        if not tag or not self.current_example:
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
        for tag in self.tags_by_example.get(self.current_example, []):
            chip = ctk.CTkButton(
                self._tags_chip_frame,
                text=f"{tag} ✕",
                width=1,
                font=ctk.CTkFont(size=11),
                fg_color="#1565C0",
                hover_color="#0D47A1",
                command=lambda t=tag: self._remove_tag_from_current(t),
            )
            chip.pack(side="left", padx=2)

    # =========================================================================
    # Abrir ejemplos / historial
    # =========================================================================

    def _browse_file(self):
        filepath = filedialog.askopenfilename(
            title="Seleccionar archivo SOFA",
            filetypes=[("Archivos SOFA", "*.scn *.py *.xml"), ("Todos los archivos", "*.*")],
        )
        if not filepath:
            return
        rel = (os.path.relpath(filepath, self.examples_dir)
               if self.examples_dir and filepath.startswith(self.examples_dir)
               else filepath)
        self.current_example = rel
        self._open_example()
        self._save_to_history(filepath)

    def _open_example(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return
        candidate = (os.path.join(self.examples_dir, self.current_example)
                     if self.examples_dir else self.current_example)
        if not os.path.exists(candidate):
            candidate = self.current_example
            if not os.path.exists(candidate):
                messagebox.showerror("Error", f"No se encontró el archivo:\n{self.current_example}")
                return
        if not self.sofa_executable or not os.path.exists(self.sofa_executable):
            messagebox.showerror(
                "SOFA no configurado",
                "No se encontró runSofa.exe.\nVe a ⚙ Configuración.",
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
            self._console_log(f"▶ Abriendo: {os.path.basename(candidate)}\n", "OK")
            self._console_status.configure(
                text=f"Simulación activa: {os.path.basename(candidate)}  |  PID {proc.pid}")
            self._switch_tab("console")
            threading.Thread(target=self._stream_sofa_output, args=(proc,), daemon=True).start()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo abrir el ejemplo:\n{exc}")

    def _build_sofa_env(self) -> dict:
        import copy
        env = copy.deepcopy(os.environ)
        exe_path = Path(self.sofa_executable)
        library_bin = exe_path.parent
        library = library_bin.parent
        conda_env = library.parent
        extra = [
            str(library_bin),
            str(library / "mingw-w64" / "bin"),
            str(conda_env / "bin"),
            str(conda_env / "Scripts"),
            str(conda_env),
        ]
        env["PATH"] = os.pathsep.join(extra) + os.pathsep + env.get("PATH", "")
        env.setdefault("SOFA_ROOT", str(library))
        env.setdefault("SOFAPLUGIN_PATH", str(library / "lib" / "sofa" / "plugins"))
        return env

    def _save_to_history(self, filepath: str):
        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass
        if filepath in history:
            history.remove(filepath)
        history.insert(0, filepath)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(history[:30], f, indent=2, ensure_ascii=False)
        self.root.after(0, self._load_history)

    def _open_from_history_path(self, path: str):
        if not os.path.exists(path):
            messagebox.showerror("Error", f"No se encontró:\n{path}")
            return
        self.current_example = (
            os.path.relpath(path, self.examples_dir)
            if self.examples_dir and path.startswith(self.examples_dir)
            else path
        )
        self._open_example()

    def _clear_history(self):
        if messagebox.askyesno("Confirmar", "¿Deseas limpiar el historial?"):
            if os.path.exists(self.history_file):
                os.remove(self.history_file)
            for w in self._history_scroll.winfo_children():
                w.destroy()

    def _verify_installation(self, silent: bool = False):
        errors = []
        if not self.sofa_executable or not os.path.exists(self.sofa_executable):
            errors.append("runSofa.exe no encontrado.\nVe a ⚙ Configuración.")
        if not self.examples_dir or not os.path.exists(self.examples_dir):
            errors.append("Carpeta de ejemplos no encontrada.\nVe a ⚙ Configuración.")
        if errors and not silent:
            messagebox.showwarning("Configuración incompleta", "\n\n".join(errors))

    # =========================================================================
    # Vista previa
    # =========================================================================

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
                text="Sin vista previa.\nUsa 'Asignar imagen' para agregar una.",
                fill="#555555", font=("Arial", 10),
            )
            self._preview_title.configure(text=example_name, text_color="gray")
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(img_path)
            self.preview_canvas.update_idletasks()
            cw = self.preview_canvas.winfo_width() or 400
            ch = self.preview_canvas.winfo_height() or 300
            img.thumbnail((cw, ch), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._preview_image_ref = photo
            self.preview_canvas.create_image(cw // 2, ch // 2, anchor="center", image=photo)
            self._preview_title.configure(text=os.path.basename(img_path), text_color="white")
        except ImportError:
            self.preview_canvas.create_text(
                10, 10, anchor="nw",
                text="Instala Pillow:\nconda install pillow",
                fill="#dcdcaa", font=("Consolas", 9),
            )
        except Exception as exc:
            self.preview_canvas.create_text(
                10, 10, anchor="nw",
                text=f"Error al cargar imagen:\n{exc}",
                fill="#f48771", font=("Consolas", 9),
            )

    def _assign_preview_image(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return
        src = filedialog.askopenfilename(
            title="Seleccionar imagen de preview",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg"), ("Todos", "*.*")],
        )
        if not src:
            return
        import shutil
        base = os.path.splitext(os.path.basename(self.current_example))[0]
        ext = os.path.splitext(src)[1].lower()
        dest = os.path.join(self._previews_dir(), base + ext)
        try:
            shutil.copy2(src, dest)
            self._show_preview(self.current_example)
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo copiar la imagen:\n{exc}")

    # =========================================================================
    # Consola
    # =========================================================================

    def _stream_sofa_output(self, proc):
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                lu = line.upper()
                tag = ("ERROR" if "[ERROR]" in lu or "ERROR:" in lu
                       else "WARNING" if "[WARNING]" in lu
                       else "DIM" if line.startswith("[#")
                       else "INFO")
                self.root.after(0, lambda l=line, t=tag: self._console_log(l + "\n", t))
        except Exception:
            pass
        finally:
            self.root.after(0, lambda: self._console_status.configure(
                text="Simulación finalizada."))

    def _console_log(self, text: str, tag: str = "INFO"):
        self.console_text.configure(state="normal")
        self.console_text.insert("end", text, tag)
        self.console_text.see("end")
        self.console_text.configure(state="disabled")

    def _clear_console(self):
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        self.console_text.configure(state="disabled")
        self._console_status.configure(text="Sin simulación activa.")

    def _save_log(self):
        content = self.console_text.get("1.0", "end").strip()
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
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo guardar:\n{exc}")

    # =========================================================================
    # Comentarios / notas
    # =========================================================================

    def _safe_update_comments(self, comments):
        self.root.after(0, lambda: self._update_comments_display(comments))

    def _clear_comments_frame(self):
        for w in self.comments_scroll.winfo_children():
            w.destroy()

    def _update_comments_display(self, comments: dict):
        self._clear_comments_frame()

        group_text = (f"👥 Grupo: {self.active_group_name}"
                      if self.active_group_id else "🌐 Notas globales")
        ctk.CTkLabel(self.comments_scroll, text=group_text,
                     font=ctk.CTkFont(size=11), text_color="gray").pack(
            anchor="w", pady=(2, 6))

        if not comments:
            ctk.CTkLabel(self.comments_scroll,
                         text="No hay notas para este ejemplo.",
                         text_color="gray").pack(pady=10)
            return

        self.current_comments = comments
        children_map = {}
        for cid, c in comments.items():
            children_map.setdefault(c.get("parent_id"), []).append(cid)

        def display_thread(parent_id=None, level=0):
            if parent_id not in children_map:
                return
            for cid in sorted(children_map[parent_id],
                               key=lambda x: comments[x].get("timestamp", 0),
                               reverse=True):
                c = comments[cid]
                user = c.get("user", "Anónimo")
                text = c.get("text", "")
                ts = c.get("timestamp", "")
                if isinstance(ts, dict):
                    ts = "Recién guardado"
                elif isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(ts / 1000).strftime("%d/%m/%Y %H:%M")

                user_color = _color_for_user(user)
                indent = level * 16

                card = ctk.CTkFrame(self.comments_scroll,
                                    border_width=1,
                                    border_color=("gray70","gray30"))
                card.pack(fill="x", pady=3, padx=(indent, 0))

                # Barra de color lateral
                import tkinter as tk
                bar = tk.Frame(card, bg=user_color, width=4)
                bar.pack(side="left", fill="y")

                inner = ctk.CTkFrame(card, fg_color="transparent")
                inner.pack(side="left", fill="both", expand=True, padx=8, pady=6)

                # Cabecera
                hdr = ctk.CTkFrame(inner, fg_color="transparent")
                hdr.pack(fill="x")

                # Avatar
                initials = "".join(w[0] for w in user.split() if w).upper()[:2] or "?"
                av = tk.Canvas(hdr, width=26, height=26,
                               highlightthickness=0, bg=hdr.cget("bg") if False else "#2b2b2b")
                av.create_oval(1, 1, 25, 25, fill=user_color, outline="")
                av.create_text(13, 13, text=initials, fill="white",
                               font=("Arial", 8, "bold"))
                av.pack(side="left", padx=(0, 6))

                ctk.CTkLabel(hdr, text=user,
                             font=ctk.CTkFont(size=12, weight="bold"),
                             text_color=user_color).pack(side="left")
                ctk.CTkLabel(hdr, text=f"  🕒 {ts}",
                             font=ctk.CTkFont(size=10), text_color="gray").pack(side="left")

                ctk.CTkLabel(inner, text=text, wraplength=380,
                             justify="left", anchor="w",
                             font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(4, 4))

                btn_row = ctk.CTkFrame(inner, fg_color="transparent")
                btn_row.pack(anchor="w")

                if user == self.current_user:
                    ctk.CTkButton(btn_row, text="✏ Editar", width=80,
                                  font=ctk.CTkFont(size=11),
                                  fg_color=("gray70","gray30"),
                                  command=lambda cid=cid: self._start_edit_comment(cid)
                                  ).pack(side="left", padx=2)
                    ctk.CTkButton(btn_row, text="🗑 Borrar", width=80,
                                  font=ctk.CTkFont(size=11),
                                  fg_color="#b71c1c",
                                  command=lambda cid=cid: self._delete_comment(cid)
                                  ).pack(side="left", padx=2)

                ctk.CTkButton(btn_row, text="↩ Responder", width=100,
                              font=ctk.CTkFont(size=11),
                              fg_color=("gray70","gray30"),
                              command=lambda cid=cid: self._start_reply_comment(cid)
                              ).pack(side="left", padx=2)

                display_thread(cid, level + 1)

        display_thread()

    def _start_edit_comment(self, comment_id: str):
        if comment_id not in self.current_comments:
            return
        c = self.current_comments[comment_id]
        if c.get("user") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo puedes editar tus comentarios.")
            return
        self.editing_comment_id = comment_id
        self.replying_to_comment_id = None
        self.new_comment.delete("1.0", "end")
        self.new_comment.insert("end", c.get("text", ""))
        self.btn_save.configure(text="💾 Guardar cambios")
        self.btn_cancel.configure(state="normal")
        self._reply_label.configure(text=f"✏ Editando comentario de {c.get('user', '')}:")

    def _delete_comment(self, comment_id: str):
        if comment_id not in self.current_comments:
            return
        if self.current_comments[comment_id].get("user") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo puedes borrar tus comentarios.")
            return
        if not messagebox.askyesno("Confirmar", "¿Borrar este comentario?"):
            return
        try:
            self.firebase.delete_comment(self.current_example, comment_id, self.active_group_id)
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo borrar:\n{exc}")

    def _start_reply_comment(self, comment_id: str):
        if comment_id not in self.current_comments:
            return
        self.replying_to_comment_id = comment_id
        self.editing_comment_id = None
        user = self.current_comments[comment_id].get("user", "")
        self.new_comment.delete("1.0", "end")
        self.new_comment.insert("end", f"@{user} ")
        self.btn_save.configure(text="↩ Guardar respuesta")
        self.btn_cancel.configure(state="normal")
        self._reply_label.configure(text=f"↩ Respondiendo a {user}:")

    def _cancel_edit_or_reply(self):
        self.editing_comment_id = None
        self.replying_to_comment_id = None
        self.new_comment.delete("1.0", "end")
        self.btn_save.configure(text="💾 Guardar nota")
        self.btn_cancel.configure(state="disabled")
        self._reply_label.configure(text="Añadir nueva nota:")

    def _save_comment(self):
        if not self.current_example:
            messagebox.showwarning("Advertencia", "Selecciona un ejemplo primero.")
            return
        text = self.new_comment.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Advertencia", "La nota no puede estar vacía.")
            return
        if not self.firebase:
            messagebox.showerror("Sin conexión", "Firebase no está conectado.")
            return
        try:
            if self.editing_comment_id:
                self.firebase.update_comment(
                    self.current_example, self.editing_comment_id, text, self.active_group_id)
            else:
                self.firebase.save_comment(
                    self.current_example, self.current_user, text,
                    self.replying_to_comment_id, self.active_group_id)
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo guardar:\n{exc}")
            return
        self._cancel_edit_or_reply()

    # =========================================================================
    # Grupos colaborativos (lógica)
    # =========================================================================

    def _refresh_my_groups(self):
        if not self.firebase:
            return
        try:
            groups = self.firebase.get_my_groups(self.current_user)
            self._my_groups = groups
            self.root.after(0, self._render_groups_list)
        except Exception as exc:
            self.root.after(0, lambda: self._groups_status_label.configure(
                text=f"Error al cargar grupos: {exc}"))

    def _selected_group_id(self) -> Optional[str]:
        return self._selected_group_ui_id

    def _create_group(self):
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
            self._groups_status_label.configure(text=f"✅ Grupo '{name}' creado.")
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo crear el grupo:\n{exc}")

    def _activate_selected_group(self):
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo de la lista.")
            return
        gdata = self._my_groups.get(gid, {})
        name = gdata.get("name", gid)
        self.active_group_id = gid
        self.active_group_name = name
        self._active_group_label.configure(text=f"👥 {name}")
        self._groups_status_label.configure(text=f"Grupo activo: {name}")
        self._render_groups_list()
        if self.current_example and self.firebase:
            self._reload_comments_for_current()

    def _activate_global(self):
        self.active_group_id = None
        self.active_group_name = "Global"
        self._active_group_label.configure(text="🌐 Global")
        self._groups_status_label.configure(text="Modo global activo.")
        self._render_groups_list()
        if self.current_example and self.firebase:
            self._reload_comments_for_current()

    def _delete_selected_group(self):
        if not self.firebase:
            return
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo.")
            return
        gdata = self._my_groups.get(gid, {})
        if gdata.get("owner") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo el creador puede eliminar el grupo.")
            return
        name = gdata.get("name", gid)
        if not messagebox.askyesno("Confirmar", f"¿Eliminar el grupo '{name}'?"):
            return
        try:
            self.firebase.delete_group(gid)
            if self.active_group_id == gid:
                self._activate_global()
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
            self._groups_status_label.configure(text=f"Grupo '{name}' eliminado.")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo eliminar:\n{exc}")

    def _add_member_to_selected(self):
        if not self.firebase:
            return
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo.")
            return
        username = self._add_member_var.get().strip()
        if not username:
            messagebox.showwarning("Advertencia", "Escribe el nombre de usuario.")
            return
        gdata = self._my_groups.get(gid, {})
        if gdata.get("owner") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo el creador puede agregar miembros.")
            return
        try:
            self.firebase.add_member(gid, username)
            self._add_member_var.set("")
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
            self._groups_status_label.configure(text=f"Usuario '{username}' agregado.")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo agregar:\n{exc}")

    def _remove_member_from_selected(self):
        if not self.firebase:
            return
        gid = self._selected_group_id()
        if not gid:
            messagebox.showwarning("Advertencia", "Selecciona un grupo.")
            return
        username = self._add_member_var.get().strip()
        if not username:
            messagebox.showwarning("Advertencia", "Escribe el nombre de usuario a remover.")
            return
        if username == self.current_user:
            messagebox.showwarning("Advertencia", "No puedes removerte a ti mismo.")
            return
        gdata = self._my_groups.get(gid, {})
        if gdata.get("owner") != self.current_user:
            messagebox.showwarning("Permiso denegado", "Solo el creador puede remover miembros.")
            return
        try:
            self.firebase.remove_member(gid, username)
            self._add_member_var.set("")
            threading.Thread(target=self._refresh_my_groups, daemon=True).start()
            self._groups_status_label.configure(text=f"Usuario '{username}' removido.")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo remover:\n{exc}")

    def _show_group_picker(self):
        if not self.firebase:
            messagebox.showerror("Sin conexión", "Firebase no está conectado.")
            return
        if not self._my_groups:
            messagebox.showinfo("Sin grupos", "No perteneces a ningún grupo.\n"
                                "Ve a 👥 Grupos para crear uno.")
            return

        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Seleccionar grupo")
        dlg.geometry("360x360")
        dlg.resizable(False, False)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Selecciona el grupo activo:",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(padx=20, pady=(16, 8))

        scroll = ctk.CTkScrollableFrame(dlg, height=200)
        scroll.pack(fill="both", expand=True, padx=20)

        group_keys = [None] + list(self._my_groups.keys())

        def _pick(gid):
            if gid is None:
                self._activate_global()
            else:
                gdata = self._my_groups.get(gid, {})
                self.active_group_id = gid
                self.active_group_name = gdata.get("name", gid)
                self._active_group_label.configure(text=f"👥 {self.active_group_name}")
                if self.current_example:
                    self._reload_comments_for_current()
            dlg.destroy()

        ctk.CTkButton(scroll, text="🌐 Global (notas compartidas con todos)",
                      anchor="w", fg_color="transparent",
                      hover_color=("gray75","gray25"),
                      command=lambda: _pick(None)).pack(fill="x", pady=2)

        for gid, gdata in self._my_groups.items():
            active = " ✅" if gid == self.active_group_id else ""
            ctk.CTkButton(scroll,
                          text=f"👥 {gdata.get('name', gid)}{active}",
                          anchor="w", fg_color="transparent",
                          hover_color=("gray75","gray25"),
                          command=lambda g=gid: _pick(g)).pack(fill="x", pady=2)

        ctk.CTkButton(dlg, text="Cerrar",
                      fg_color=("gray70","gray30"),
                      command=dlg.destroy).pack(pady=12)

    def _reload_comments_for_current(self):
        if not self.current_example or not self.firebase:
            return

        def _fetch():
            gid = self.active_group_id
            comments = self.firebase.get_comments(self.current_example, gid)
            self.root.after(0, lambda: self._update_comments_display(comments))
            self.firebase.listen_updates(self.current_example, self._safe_update_comments, gid)

        threading.Thread(target=_fetch, daemon=True).start()

    # =========================================================================
    # Configuración
    # =========================================================================

    def _browse_path(self, var, kind: str):
        path = (filedialog.askopenfilename(
                    title="Seleccionar runSofa.exe",
                    filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")])
                if kind == "exe"
                else filedialog.askdirectory(title="Seleccionar carpeta de ejemplos"))
        if path:
            var.set(path)

    def _load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.sofa_executable = cfg.get("sofa_executable", "")
                self.examples_dir = cfg.get("examples_dir", "")
                self.current_user = cfg.get("current_user", os.getlogin())
                self.notification_enabled = cfg.get("notification_enabled", True)
                print("[Config] Configuración cargada desde sofa_config.json")
                return
            except Exception as exc:
                print(f"[Config] Error al leer config: {exc}")
        exe, exdir = _find_sofa_installation()
        self.sofa_executable = exe
        self.examples_dir = exdir
        self.current_user = os.getlogin()
        self.notification_enabled = True

    def _save_config(self):
        cfg = {
            "sofa_executable": self.sofa_executable,
            "examples_dir": self.examples_dir,
            "current_user": self.current_user,
            "notification_enabled": self.notification_enabled,
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[Config] Error al guardar config: {exc}")

    def _apply_settings(self):
        self.sofa_executable = self._exe_var.get().strip()
        self.examples_dir = self._dir_var.get().strip()
        self.current_user = self._user_var.get().strip() or os.getlogin()
        self._user_sidebar_label.configure(text=f"👤 {self.current_user}")
        self._load_examples()
        self._verify_installation(silent=True)
        self._save_config()
        self._settings_status.configure(text="✅ Configuración guardada.")

    def _on_close(self):
        self._save_config()
        self.root.destroy()

    # =========================================================================
    # Exportar notas
    # =========================================================================

    def _build_notes_markdown(self) -> str:
        comments = self.current_comments
        example = self.current_example or "Sin ejemplo"
        group = f"Grupo: {self.active_group_name}" if self.active_group_id else "Global"
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
        for cid, c in comments.items():
            children_map.setdefault(c.get("parent_id"), []).append(cid)

        def walk(parent_id=None, level=0):
            if parent_id not in children_map:
                return
            for cid in sorted(children_map[parent_id],
                               key=lambda x: comments[x].get("timestamp", 0)):
                c = comments[cid]
                user = c.get("user", "Anónimo")
                text = c.get("text", "")
                ts = c.get("timestamp", "")
                if isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(ts / 1000).strftime("%d/%m/%Y %H:%M")
                indent = "  " * level
                lines.append(f"{indent}**{user}** — {ts}")
                for ln in text.splitlines():
                    lines.append(f"{indent}{ln}")
                lines.append("")
                walk(cid, level + 1)

        walk()
        return "\n".join(lines)

    def _export_notes(self):
        if not self.current_comments:
            messagebox.showinfo("Exportar", "No hay notas que exportar.")
            return
        filepath = filedialog.asksaveasfilename(
            title="Exportar notas",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Texto", "*.txt"), ("Todos", "*.*")],
            initialfile=f"notas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self._build_notes_markdown())
            messagebox.showinfo("Exportado", f"Notas guardadas en:\n{filepath}")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo exportar:\n{exc}")


# ===========================================================================
# Entry point
# ===========================================================================

def main():
    root = ctk.CTk()
    SOFAInterface(root)
    root.mainloop()


if __name__ == "__main__":
    main()
