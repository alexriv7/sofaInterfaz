# SOFA Interface - Gestor Colaborativo para Simulación Médica
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Interfaz gráfica para SOFA Framework con funciones colaborativas en tiempo real usando Firebase.
Instalación con Anaconda

1. Crear entorno:

conda create -n sofa python=3.9
conda activate sofa

2. Instalar dependencias:
   
conda install -c conda-forge tk firebase-admin plyer

3.Clonar repositorio :

git clone https://github.com/alexriv7/sofaInterfaz.git
cd sofaInterfaz

4. Configurar firebase:
   
Crear firebase-key.json en la raíz del proyecto
Obtener credenciales desde Firebase Console
https://firebase.google.com/

5.Ejecutar proyecto :

python src/interfaz_sofa.py

