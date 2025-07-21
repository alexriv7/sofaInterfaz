# README - Interfaz SOFA Manager 

## Instrucciones para instalación y ejecución en Windows

Requisitos previos 
1. **Python 3.7+** instalado (verificar con `python --version`)
2. **Anaconda/Miniconda** ([Descargar aquí](https://www.anaconda.com/download))
3. **Git** ([Descargar aquí](https://git-scm.com/download/win))
4. **Compilador C++** (Visual Studio 2019+ para Windows)
5. 10GB+ espacio libre en disco



Instalación por pasos:

1. Instalar SOFA Framework

git clone -b v24.12.00 https://github.com/sofa-framework/sofa.git sofa/src
cd sofa/src
mkdir build && cd build
cmake -G "Visual Studio 16 2019" -DCMAKE_BUILD_TYPE=Release ..
cmake --build . --config Release --target install

2. Configurar entorno Anaconda
bash
conda create -n sofa_env python=3.8
conda activate sofa_env
conda install -c conda-forge cmake
3. Instalar dependencias Python
bash
pip install firebase-admin plyer pillow tk
4. Clonar repositorio de la interfaz
bash
git clone https://github.com/alexriv7/sofaInterfaz.git
cd sofaInterfaz
5. Configurar rutas críticas
Editar interfaz_sofa.py y actualizar:


# Para instalación estándar de Anaconda:
self.sofa_executable = r"C:\Users\TU_USUARIO\anaconda3\envs\sofa_env\Library\bin\runSofa.exe"
self.examples_dir = r"C:\Users\TU_USUARIO\anaconda3\envs\sofa_env\Library\share\sofa\examples"

# Para instalación manual:
# self.sofa_executable = r"C:\sofa\build\bin\Release\runSofa.exe"
# self.examples_dir = r"C:\sofa\src\examples"

# Ejecución del programa
Abrir Anaconda Prompt como Administrador

Ejecutar:

bash
conda activate sofa_env
cd C:\ruta\a\sofaInterfaz
python interfaz_sofa.py

 Configuración Firebase
Colocar firebase-key.json en la raíz del proyecto

Configurar reglas en Firebase Console:

json
{
  "rules": {
    "sofa_comments": {
      ".read": "auth != null",
      ".write": "auth != null"
    }
  }
}




