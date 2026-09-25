from fastapi import APIRouter, Depends
from app.models.search_models import SearchRequest, SearchResponse, FilterOptions
from app.models.user_models import UserOut
from app.services.search_service import SearchService
from app.security.microsoft_auth import auth_service, require_authenticated

router = APIRouter()

def get_search_service() -> SearchService:
    return SearchService()

@router.post("/", response_model=SearchResponse)
async def search_documents(
    body: SearchRequest,
    service: SearchService = Depends(get_search_service),
    user: UserOut = Depends(auth_service.get_current_user),
    _=Depends(require_authenticated),
):
    """
    Búsqueda semántica con filtros facetados completos.
    Disponible para todos los roles (technical, basic, admin).

    Filtros disponibles:
    - estado_vigencia, tipo_nombramiento, area, subarea
    - beneficio, sede_campus (muchos a muchos), departamento
    - tipo_documento, tipo_decision, tipo_sesion
    - carrera, tipo_programa, nivel_academico
    - categoria, macro_categoria
    - fechas: creacion, designacion, inicio_vigencia, fin_vigencia
    - metadatos: num_acuerdo, num_sesion, version
    """
    return await service.search(body)

@router.get("/filters", response_model=FilterOptions)
async def get_filter_options(
    service: SearchService = Depends(get_search_service),
    _=Depends(require_authenticated),
):
    """
    Devuelve todos los valores disponibles para poblar los dropdowns del frontend.
    Incluye: vigencia, roles/nombramientos, áreas, beneficios, sedes, departamentos,
    tipos de documento/decisión/sesión, carreras, categorías.
    """
    return await service.get_filter_options()
