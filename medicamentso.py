#1- Importación de librerías
import os
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.io as pio
from dash import Dash, html, dcc, Input, Output, dash_table
from dash.dash_table import FormatTemplate
import dash_bootstrap_components as dbc

#2- Conexión a la base de datos SQLite
# Busca la base en la misma carpeta de este archivo (necesario para Posit)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "medicamentos.db")
if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
    raise FileNotFoundError(f"No se encontró la base de datos en: {DB_PATH}")

# Paleta de azules del tablero
AZUL_OSCURO = "#0B2545"
AZUL = "#13579B"
AZUL_MEDIO = "#3D8FD1"
AZUL_CLARO = "#8DC3EC"
AZUL_FONDO = "#EEF4FA"
GRIS_TEXTO = "#5A6B7B"
PALETA = [AZUL, AZUL_MEDIO, AZUL_CLARO, AZUL_OSCURO, "#B9D7F0"]

# Estilo común para todas las gráficas
pio.templates["eps"] = pio.templates["plotly_white"]
pio.templates["eps"].layout.update(
    font=dict(family="Source Sans 3, Segoe UI, sans-serif", color=AZUL_OSCURO, size=13),
    title=dict(font=dict(size=17, color=AZUL_OSCURO)),
    colorway=PALETA,
    margin=dict(l=10, r=10, t=55, b=10),
)
pio.templates.default = "eps"

# Vista con los datos limpios (no modifica la base original):
#  - grupo_fco_economico vacío: se completa con el grupo que tiene el mismo
#    medicamento en otras filas; si nunca lo tiene, queda "SIN CLASIFICAR".
#  - municipio, departamento y regional con "0" o vacíos: se marcan "Sin dato".
#  - tipo_entrega vacío: se agrupa con DOMICILIARIO.
VISTA_LIMPIA = """
CREATE TEMP VIEW IF NOT EXISTS dispensacion_limpia AS
WITH grupos AS (
    SELECT descripcion,
           MAX(NULLIF(TRIM(grupo_fco_economico), '')) AS grupo
    FROM dispensacion
    GROUP BY descripcion
)
SELECT d.id, d.distribuidor, d.fecha_entrega, d.subcuenta, d.formula,
       CASE WHEN TRIM(COALESCE(d.regional_caf, '')) IN ('', '0')
            THEN 'Sin dato' ELSE d.regional_caf END AS regional_caf,
       CASE WHEN TRIM(COALESCE(d.departamento_caf, '')) IN ('', '0')
            THEN 'Sin dato' ELSE d.departamento_caf END AS departamento_caf,
       CASE WHEN TRIM(COALESCE(d.municipio_caf, '')) IN ('', '0')
            THEN 'Sin dato' ELSE d.municipio_caf END AS municipio_caf,
       d.descripcion, d.familia,
       COALESCE(NULLIF(TRIM(d.grupo_fco_economico), ''), g.grupo, 'SIN CLASIFICAR')
            AS grupo_fco_economico,
       d.subgrupo_fco_economico, d.cronico, d.cantidad, d.precio, d.costo_total,
       d.contrato, d.pbs,
       -- tipo_entrega vacío (se veía como "2" en la gráfica) se asigna a DOMICILIARIO
       CASE WHEN TRIM(COALESCE(d.tipo_entrega, '')) IN ('', '2')
            THEN 'DOMICILIARIO' ELSE d.tipo_entrega END AS tipo_entrega
FROM dispensacion d
LEFT JOIN grupos g ON d.descripcion = g.descripcion
"""


def consultar(query, params=None):
    """Abre la conexión, crea la vista limpia, ejecuta la consulta y cierra.
    Se abre en cada consulta porque Dash ejecuta los callbacks en otros hilos."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(VISTA_LIMPIA)
        return pd.read_sql(query, conn, params=params)

# Tabla: dispensacion
# Columnas usadas: id, fecha_entrega, formula, regional_caf, departamento_caf, descripcion,
#                  grupo_fco_economico, costo_total, pbs, tipo_entrega

#3- Número de personas con dispensaciones (variable id)
n_personas = consultar("""
    SELECT COUNT(DISTINCT id) FROM dispensacion_limpia
""").iloc[0, 0]
print(f"Número de personas con dispensaciones: {n_personas:,}")

#4- Número de fórmulas distintas dispensadas (variable formula)
n_formulas = consultar("""
    SELECT COUNT(DISTINCT formula) FROM dispensacion_limpia
""").iloc[0, 0]
print(f"Número de fórmulas distintas dispensadas: {n_formulas:,}")

#5- Costo promedio de una fórmula dispensada
costo_prom_formula = consultar("""
    SELECT SUM(costo_total) * 1.0 / COUNT(DISTINCT formula) FROM dispensacion_limpia
""").iloc[0, 0]
print(f"Costo promedio por fórmula: ${costo_prom_formula:,.2f}")

#6- Dispensación de medicamentos en el tiempo
dispensacion_mes = consultar("""
    SELECT strftime('%Y-%m', fecha_entrega) AS mes,
           COUNT(DISTINCT formula) AS formulas
    FROM dispensacion_limpia
    GROUP BY mes ORDER BY mes
""")
fig_tiempo = px.line(dispensacion_mes, x="mes", y="formulas", markers=True,
                     title="Fórmulas dispensadas por mes",
                     labels={"mes": "Mes", "formulas": "Fórmulas dispensadas"})
fig_tiempo.update_traces(line=dict(width=3), marker=dict(size=7))

#7- Top de medicamentos con mayor costo total
top_medicamentos = consultar("""
    SELECT descripcion, SUM(costo_total) AS costo
    FROM dispensacion_limpia
    GROUP BY descripcion ORDER BY costo DESC LIMIT 10
""")
fig_top = px.bar(top_medicamentos, x="costo", y="descripcion", orientation="h",
                 title="Top 10 medicamentos con mayor costo total",
                 labels={"costo": "Costo total", "descripcion": "Medicamento"})
fig_top.update_layout(yaxis={"categoryorder": "total ascending"})
fig_top.update_xaxes(tickprefix="$", tickformat=",.2f")

#8- Costo según PBS / No PBS (top 10 de cada uno)
costo_pbs = consultar("""
    SELECT plan, puesto, medicamento, costo_total
    FROM (
        SELECT CASE WHEN pbs = 'SI' THEN 'PBS' ELSE 'No PBS' END AS plan,
               descripcion AS medicamento,
               SUM(costo_total) AS costo_total,
               ROW_NUMBER() OVER (
                   PARTITION BY CASE WHEN pbs = 'SI' THEN 'PBS' ELSE 'No PBS' END
                   ORDER BY SUM(costo_total) DESC
               ) AS puesto
        FROM dispensacion_limpia
        GROUP BY plan, descripcion
    )
    WHERE puesto <= 10
    ORDER BY plan DESC, puesto
""")
top_pbs = costo_pbs[costo_pbs["plan"] == "PBS"].drop(columns="plan")
top_no_pbs = costo_pbs[costo_pbs["plan"] == "No PBS"].drop(columns="plan")

#9- Costo por departamento de dispensación
# Los "0" ya vienen como "Sin dato" desde la vista limpia (62% del costo total)
SQL_DEPARTAMENTO = """
    SELECT departamento_caf AS departamento,
           SUM(costo_total) AS costo
    FROM dispensacion_limpia {where}
    GROUP BY departamento ORDER BY costo DESC
"""
costo_departamento = consultar(SQL_DEPARTAMENTO.format(where=""))
fig_municipio = px.bar(costo_departamento, x="costo", y="departamento", orientation="h",
                       title="Costo por departamento de dispensación",
                       labels={"costo": "Costo total", "departamento": "Departamento"})
fig_municipio.update_layout(yaxis={"categoryorder": "total ascending"})
fig_municipio.update_xaxes(tickprefix="$", tickformat=",.2f")

#10- Costo según tipo de entrega
costo_entrega = consultar("""
    SELECT tipo_entrega, SUM(costo_total) AS costo
    FROM dispensacion_limpia
    GROUP BY tipo_entrega ORDER BY costo DESC
""")
fig_entrega = px.pie(costo_entrega, names="tipo_entrega", values="costo", hole=0.55,
                     title="Costo según tipo de entrega",
                     color_discrete_sequence=[AZUL, AZUL_CLARO, AZUL_MEDIO])
fig_entrega.update_traces(hovertemplate="%{label}<br>$%{value:,.2f}<br>%{percent}")

#11- Opciones de los filtros (se excluyen valores vacíos)
op_grupos = consultar("""
    SELECT DISTINCT grupo_fco_economico FROM dispensacion_limpia
    WHERE grupo_fco_economico IS NOT NULL ORDER BY 1
""").iloc[:, 0].tolist()

op_anios = consultar("""
    SELECT DISTINCT strftime('%Y', fecha_entrega) FROM dispensacion_limpia
    WHERE fecha_entrega IS NOT NULL ORDER BY 1
""").iloc[:, 0].tolist()

op_meses = consultar("""
    SELECT DISTINCT strftime('%m', fecha_entrega) FROM dispensacion_limpia
    WHERE fecha_entrega IS NOT NULL ORDER BY 1
""").iloc[:, 0].tolist()

op_regionales = consultar("""
    SELECT DISTINCT regional_caf FROM dispensacion_limpia
    WHERE regional_caf IS NOT NULL ORDER BY 1
""").iloc[:, 0].tolist()


def construir_filtro(grupos, anios, meses, regionales):
    """Arma el WHERE según los filtros elegidos. Si un filtro está vacío, no se aplica."""
    condiciones, params = [], []

    def agregar(columna, valores):
        if valores:
            marcadores = ",".join("?" * len(valores))
            condiciones.append(f"{columna} IN ({marcadores})")
            params.extend(valores)

    agregar("grupo_fco_economico", grupos)
    agregar("strftime('%Y', fecha_entrega)", anios)
    agregar("strftime('%m', fecha_entrega)", meses)
    agregar("regional_caf", regionales)

    where = "WHERE " + " AND ".join(condiciones) if condiciones else ""
    return where, params


# ---------------- TABLERO ----------------
app = Dash(__name__, external_stylesheets=[
    dbc.themes.BOOTSTRAP,
    "https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap",
])
app.title = "Dispensación de medicamentos 2020-2021"
server = app.server  # para el despliegue

nombres_meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
                 "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Función para crear una tarjeta de indicador
def tarjeta(titulo, id_valor):
    return dbc.Card(dbc.CardBody([
        html.P(titulo, style={"color": GRIS_TEXTO, "marginBottom": "4px"}),
        html.H3(id=id_valor, style={"color": AZUL, "fontWeight": 700, "margin": 0}),
    ]), style={"border": "none", "borderLeft": f"6px solid {AZUL_MEDIO}",
               "boxShadow": "0 2px 8px rgba(11,37,69,0.08)"})


# Contenedor blanco para cada gráfica
def caja(componente):
    return dbc.Card(componente, body=True, className="mb-4",
                    style={"border": "none", "boxShadow": "0 2px 8px rgba(11,37,69,0.08)"})

# Columnas de las tablas PBS / No PBS con formato en pesos
columnas = [
    {"name": "Puesto", "id": "puesto"},
    {"name": "Medicamento", "id": "medicamento"},
    {"name": "Costo total", "id": "costo_total", "type": "numeric",
     "format": FormatTemplate.money(2)},
]

# Tabla interactiva: ordenar, buscar y paginar
def tabla_top(id_tabla, datos, color):
    return dash_table.DataTable(
        id=id_tabla, columns=columnas, data=datos,
        sort_action="native",      # ordenar dando clic en el encabezado
        filter_action="native",    # buscar escribiendo debajo del encabezado
        page_size=10,
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": color, "color": "white", "fontWeight": "bold"},
        style_cell={"textAlign": "left", "padding": "6px",
                    "whiteSpace": "normal", "height": "auto"},
        style_cell_conditional=[{"if": {"column_id": "costo_total"}, "textAlign": "right"}],
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": AZUL_FONDO},
            {"if": {"state": "active"}, "backgroundColor": "#DCEBF5", "border": "1px solid " + color},
        ],
    )

# Panel de filtros (puntos 9, 10 y 11)
estilo_label = {"color": "white", "fontWeight": 600, "marginTop": "16px", "marginBottom": "4px"}

filtros = html.Div([
    html.H5("Filtros", style={"color": "white", "fontWeight": 700}),
    html.Hr(style={"borderColor": AZUL_CLARO, "opacity": 0.6}),
    html.Label("Grupo farmacológico", style=estilo_label),
    dcc.Dropdown(id="f_grupo", options=op_grupos, multi=True, placeholder="Todos"),
    html.Label("Año", style=estilo_label),
    dcc.Dropdown(id="f_anio", options=op_anios, multi=True, placeholder="Todos"),
    html.Label("Mes", style=estilo_label),
    dcc.Dropdown(id="f_mes", multi=True, placeholder="Todos",
                 options=[{"label": nombres_meses[int(m) - 1], "value": m} for m in op_meses]),
    html.Label("Regional CAF", style=estilo_label),
    dcc.Dropdown(id="f_regional", options=op_regionales, multi=True, placeholder="Todos"),
    html.P("Deja un filtro vacío para ver todos los datos.",
           style={"color": AZUL_CLARO, "fontSize": "14px", "marginTop": "24px"}),
], className="p-4", style={"backgroundColor": AZUL_OSCURO, "minHeight": "100vh",
                           "position": "sticky", "top": 0, "zIndex": 1000})

# Pestaña 1: Resumen (puntos 1 a 4)
tab_resumen = html.Div([
    dbc.Row([
        dbc.Col(tarjeta("Personas con dispensaciones", "kpi_personas")),
        dbc.Col(tarjeta("Fórmulas distintas", "kpi_formulas")),
        dbc.Col(tarjeta("Costo promedio por fórmula", "kpi_costo")),
    ], className="mb-4"),
    caja(dcc.Graph(id="g_tiempo", figure=fig_tiempo)),
], className="pt-4")

# Pestaña 2: Medicamentos (puntos 5 y 6)
tab_medicamentos = html.Div([
    caja(dcc.Graph(id="g_top", figure=fig_top)),
    html.H5("Top de medicamentos por costo según PBS",
            style={"color": AZUL_OSCURO, "fontWeight": 700}),
    html.Div([
        html.Label("Cantidad de medicamentos a mostrar:", className="me-3"),
        dbc.RadioItems(id="n_top", value=10, inline=True,
                       options=[{"label": str(n), "value": n} for n in (5, 10, 20, 50)]),
    ], className="d-flex align-items-center mb-3"),
    dbc.Row([
        dbc.Col([html.H6("PBS", style={"color": AZUL, "fontWeight": 700}),
                 tabla_top("t_pbs", top_pbs.to_dict("records"), AZUL)], md=6),
        dbc.Col([html.H6("No PBS", style={"color": AZUL_MEDIO, "fontWeight": 700}),
                 tabla_top("t_no_pbs", top_no_pbs.to_dict("records"), AZUL_MEDIO)], md=6),
    ]),
], className="pt-4")

# Pestaña 3: Departamentos y entrega (puntos 7 y 8)
tab_territorio = html.Div([
    dbc.Row([
        dbc.Col(caja(dcc.Graph(id="g_municipio", figure=fig_municipio)), md=7),
        dbc.Col(caja(dcc.Graph(id="g_entrega", figure=fig_entrega)), md=5),
    ]),
], className="pt-4")

# Contenido principal con pestañas
estilo_tab = {"color": AZUL, "fontWeight": 600}
estilo_tab_activa = {"color": "white", "backgroundColor": AZUL, "fontWeight": 700}

encabezado = html.Div([
    html.H2("Dispensación de medicamentos 2020-2021",
            style={"color": "white", "fontWeight": 700, "margin": 0}),
    html.P("Tablero de seguimiento de costos para la EPS",
           style={"color": AZUL_CLARO, "margin": 0}),
], style={"background": f"linear-gradient(90deg, {AZUL} 0%, {AZUL_MEDIO} 100%)",
          "padding": "22px 28px", "borderRadius": "10px", "marginBottom": "20px"})

contenido = html.Div([
    encabezado,
    dbc.Tabs([
        dbc.Tab(tab_resumen, label="Resumen",
                label_style=estilo_tab, active_label_style=estilo_tab_activa),
        dbc.Tab(tab_medicamentos, label="Medicamentos",
                label_style=estilo_tab, active_label_style=estilo_tab_activa),
        dbc.Tab(tab_territorio, label="Departamentos y entrega",
                label_style=estilo_tab, active_label_style=estilo_tab_activa),
    ]),
], className="p-4")

app.layout = html.Div(
    dbc.Row([
        dbc.Col(filtros, md=3, lg=2),
        dbc.Col(contenido, md=9, lg=10),
    ], className="g-0"),
    style={"backgroundColor": AZUL_FONDO, "minHeight": "100vh",
           "fontFamily": "Source Sans 3, Segoe UI, sans-serif"},
)


# ---------------- CALLBACK: actualiza todo según los filtros ----------------
@app.callback(
    Output("kpi_personas", "children"),
    Output("kpi_formulas", "children"),
    Output("kpi_costo", "children"),
    Output("g_tiempo", "figure"),
    Output("g_top", "figure"),
    Output("t_pbs", "data"),
    Output("t_no_pbs", "data"),
    Output("g_municipio", "figure"),
    Output("g_entrega", "figure"),
    Input("f_grupo", "value"),
    Input("f_anio", "value"),
    Input("f_mes", "value"),
    Input("f_regional", "value"),
    Input("n_top", "value"),
)
def actualizar(grupos, anios, meses, regionales, n_top):
    where, params = construir_filtro(grupos, anios, meses, regionales)

    # Puntos 1, 2 y 3
    kpis = consultar(f"""
        SELECT COUNT(DISTINCT id) AS personas,
               COUNT(DISTINCT formula) AS formulas,
               SUM(costo_total) * 1.0 / COUNT(DISTINCT formula) AS costo_prom
        FROM dispensacion_limpia {where}
    """, params).iloc[0]
    txt_personas = f"{int(kpis['personas']):,}"
    txt_formulas = f"{int(kpis['formulas']):,}"
    txt_costo = f"${kpis['costo_prom']:,.2f}" if pd.notna(kpis["costo_prom"]) else "$0.00"

    # Punto 4
    df_tiempo = consultar(f"""
        SELECT strftime('%Y-%m', fecha_entrega) AS mes, COUNT(DISTINCT formula) AS formulas
        FROM dispensacion_limpia {where}
        GROUP BY mes ORDER BY mes
    """, params)
    f_tiempo = px.line(df_tiempo, x="mes", y="formulas", markers=True,
                       title="Fórmulas dispensadas por mes",
                       labels={"mes": "Mes", "formulas": "Fórmulas dispensadas"})
    f_tiempo.update_traces(line=dict(width=3), marker=dict(size=7))

    # Punto 5
    df_top = consultar(f"""
        SELECT descripcion, SUM(costo_total) AS costo
        FROM dispensacion_limpia {where}
        GROUP BY descripcion ORDER BY costo DESC LIMIT 10
    """, params)
    f_top = px.bar(df_top, x="costo", y="descripcion", orientation="h",
                   title="Top 10 medicamentos con mayor costo total",
                   labels={"costo": "Costo total", "descripcion": "Medicamento"})
    f_top.update_layout(yaxis={"categoryorder": "total ascending"})
    f_top.update_xaxes(tickprefix="$", tickformat=",.2f")

    # Punto 6
    df_pbs = consultar(f"""
        SELECT plan, puesto, medicamento, costo_total
        FROM (
            SELECT CASE WHEN pbs = 'SI' THEN 'PBS' ELSE 'No PBS' END AS plan,
                   descripcion AS medicamento,
                   SUM(costo_total) AS costo_total,
                   ROW_NUMBER() OVER (
                       PARTITION BY CASE WHEN pbs = 'SI' THEN 'PBS' ELSE 'No PBS' END
                       ORDER BY SUM(costo_total) DESC
                   ) AS puesto
            FROM dispensacion_limpia {where}
            GROUP BY plan, descripcion
        )
        WHERE puesto <= ?
        ORDER BY plan DESC, puesto
    """, params + [n_top])
    d_pbs = df_pbs[df_pbs["plan"] == "PBS"].drop(columns="plan").to_dict("records")
    d_no_pbs = df_pbs[df_pbs["plan"] == "No PBS"].drop(columns="plan").to_dict("records")

    # Punto 7
    df_dep = consultar(SQL_DEPARTAMENTO.format(where=where), params)
    f_mun = px.bar(df_dep, x="costo", y="departamento", orientation="h",
                   title="Costo por departamento de dispensación",
                   labels={"costo": "Costo total", "departamento": "Departamento"})
    f_mun.update_layout(yaxis={"categoryorder": "total ascending"})
    f_mun.update_xaxes(tickprefix="$", tickformat=",.2f")

    # Punto 8
    df_ent = consultar(f"""
        SELECT tipo_entrega, SUM(costo_total) AS costo
        FROM dispensacion_limpia {where}
        GROUP BY tipo_entrega ORDER BY costo DESC
    """, params)
    f_ent = px.pie(df_ent, names="tipo_entrega", values="costo", hole=0.55,
                   title="Costo según tipo de entrega",
                   color_discrete_sequence=[AZUL, AZUL_CLARO, AZUL_MEDIO])
    f_ent.update_traces(hovertemplate="%{label}<br>$%{value:,.2f}<br>%{percent}")

    return (txt_personas, txt_formulas, txt_costo,
            f_tiempo, f_top, d_pbs, d_no_pbs, f_mun, f_ent)


if __name__ == "__main__":
    app.run(debug=True)
