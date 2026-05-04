"""
Generic CRUD Router Factory

Génère automatiquement les 4 routes CRUD standard pour une entité.
Réduit la duplication de code dans les routers admin.

Usage:
    from app.common.crud_router import create_crud_router

    roles_router = create_crud_router(
        model_class=Role,
        read_schema=RoleRead,
        create_schema=RoleCreate,
        update_schema=RoleUpdate,
        prefix="/roles",
        entity_name="role",
        id_field="role_id",
        tags=["Admin - Roles"],
    )
"""
import logging
from typing import Type, TypeVar, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_admin_user
from app.models import User
from app.features.admin.repository import AdminRepository
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT

logger = logging.getLogger(__name__)

T = TypeVar('T')


def create_crud_router(
    model_class: Type[T],
    read_schema: Type[BaseModel],
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    prefix: str,
    entity_name: str,
    id_field: str = "id",
    id_type: Type = int,
    service_create: Optional[Callable] = None,
    service_update: Optional[Callable] = None,
    service_delete: Optional[Callable] = None,
    tags: Optional[list] = None,
) -> APIRouter:
    """
    Crée un router CRUD complet pour une entité.

    Génère automatiquement 4 endpoints REST :
    - GET {prefix} : Liste toutes les entités
    - POST {prefix} : Crée une nouvelle entité
    - PATCH {prefix}/{id} : Met à jour une entité
    - DELETE {prefix}/{id} : Supprime une entité

    Chaque endpoint inclut :
    - Authentification admin requise
    - Logging d'audit automatique
    - Métriques Prometheus
    - Gestion d'erreurs standardisée

    Args:
        model_class: Classe SQLAlchemy du modèle
        read_schema: Schema Pydantic pour la lecture (response)
        create_schema: Schema Pydantic pour la création (request body)
        update_schema: Schema Pydantic pour la mise à jour (request body)
        prefix: Préfixe URL (ex: "/roles")
        entity_name: Nom de l'entité pour l'audit (ex: "role")
        id_field: Nom du champ ID dans l'URL (ex: "role_id")
        id_type: Type de l'ID (int ou UUID)
        service_create: Fonction de création custom (optionnel)
        service_update: Fonction de mise à jour custom (optionnel)
        service_delete: Fonction de suppression custom (optionnel)
        tags: Tags OpenAPI (optionnel)

    Returns:
        APIRouter: Router FastAPI avec les 4 routes CRUD

    Example:
        >>> roles_router = create_crud_router(
        ...     model_class=Role,
        ...     read_schema=RoleRead,
        ...     create_schema=RoleCreate,
        ...     update_schema=RoleUpdate,
        ...     prefix="/roles",
        ...     entity_name="role",
        ...     id_field="role_id",
        ...     service_create=AdminService.create_role,
        ...     tags=["Admin - Roles"],
        ... )
        >>> router.include_router(roles_router)
    """
    router = APIRouter(tags=tags or ["Admin - CRUD"])
    endpoint_name = f"/admin{prefix}"
    entity_title = entity_name.replace("_", " ").title()

    # =========================================================================
    # GET - Liste toutes les entités
    # =========================================================================
    @router.get(
        prefix,
        response_model=list[read_schema],
        summary=f"Liste tous les {entity_name}s",
        description=f"""
Récupère la liste complète des {entity_name}s.

**Authentification requise** : Admin

**Réponse** : Liste des {entity_name}s au format JSON
        """,
        responses={
            200: {"description": f"Liste des {entity_name}s récupérée avec succès"},
            401: {"description": "Non authentifié"},
            403: {"description": "Accès refusé - rôle admin requis"},
            500: {"description": "Erreur serveur"},
        },
    )
    async def list_entities(
        admin_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        try:
            entities = await AdminRepository.get_all(
                db, model_class, limit=1000, order_by=getattr(model_class, 'id')
            )
            REQUEST_COUNT.labels(endpoint=endpoint_name, method="GET", status="200").inc()
            return entities
        except Exception as e:
            REQUEST_COUNT.labels(endpoint=endpoint_name, method="GET", status="500").inc()
            logger.error(f"Error fetching {entity_name}s: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # POST - Crée une nouvelle entité
    # =========================================================================
    @router.post(
        prefix,
        response_model=read_schema,
        status_code=201,
        summary=f"Crée un nouveau {entity_name}",
        description=f"""
Crée un nouveau {entity_name} dans la base de données.

**Authentification requise** : Admin

**Audit** : L'action est enregistrée dans les logs d'audit
        """,
        responses={
            201: {"description": f"{entity_title} créé avec succès"},
            400: {"description": "Données invalides"},
            401: {"description": "Non authentifié"},
            403: {"description": "Accès refusé - rôle admin requis"},
            409: {"description": "Conflit - entité déjà existante"},
            500: {"description": "Erreur serveur"},
        },
    )
    async def create_entity(
        data: create_schema,
        request: Request,
        admin_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        try:
            if service_create:
                new_entity = await service_create(db, data.model_dump())
            else:
                new_entity = model_class(**data.model_dump())
                db.add(new_entity)
                await db.commit()
                await db.refresh(new_entity)

            await AuditService.log_action(
                db=db,
                action_name=f'{entity_name}_created',
                user_id=admin_user.id,
                resource_type_name=entity_name,
                resource_id=None,
                details={'name': getattr(new_entity, 'name', None), 'id': new_entity.id},
                request=request
            )

            REQUEST_COUNT.labels(endpoint=endpoint_name, method="POST", status="201").inc()
            return new_entity
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            REQUEST_COUNT.labels(endpoint=endpoint_name, method="POST", status="500").inc()
            logger.error(f"Error creating {entity_name}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # PATCH - Met à jour une entité
    # =========================================================================
    @router.patch(
        f"{prefix}/{{{id_field}}}",
        response_model=read_schema,
        summary=f"Met à jour un {entity_name}",
        description=f"""
Met à jour un {entity_name} existant (mise à jour partielle).

**Authentification requise** : Admin

**Audit** : L'action est enregistrée dans les logs d'audit

Seuls les champs fournis dans le body seront mis à jour.
        """,
        responses={
            200: {"description": f"{entity_title} mis à jour avec succès"},
            400: {"description": "Données invalides"},
            401: {"description": "Non authentifié"},
            403: {"description": "Accès refusé - rôle admin requis"},
            404: {"description": f"{entity_title} non trouvé"},
            500: {"description": "Erreur serveur"},
        },
    )
    async def update_entity(
        request: Request,
        data: update_schema,
        admin_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        raw_id = request.path_params.get(id_field)
        try:
            entity_id = id_type(raw_id) if id_type != str else raw_id
            if service_update:
                updated = await service_update(db, entity_id, data.model_dump(exclude_unset=True))
            else:
                entity = await AdminRepository.get_by_id(db, model_class, entity_id)
                if not entity:
                    raise HTTPException(status_code=404, detail=f"{entity_title} not found")
                for key, value in data.model_dump(exclude_unset=True).items():
                    setattr(entity, key, value)
                await db.commit()
                await db.refresh(entity)
                updated = entity

            await AuditService.log_action(
                db=db,
                action_name=f'{entity_name}_updated',
                user_id=admin_user.id,
                resource_type_name=entity_name,
                resource_id=None,
                details={'id': entity_id, 'updates': data.model_dump(exclude_unset=True)},
                request=request
            )

            REQUEST_COUNT.labels(endpoint=endpoint_name, method="PATCH", status="200").inc()
            return updated
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            REQUEST_COUNT.labels(endpoint=endpoint_name, method="PATCH", status="500").inc()
            logger.error(f"Error updating {entity_name}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # DELETE - Supprime une entité
    # =========================================================================
    @router.delete(
        f"{prefix}/{{{id_field}}}",
        status_code=204,
        summary=f"Supprime un {entity_name}",
        description=f"""
Supprime définitivement un {entity_name} de la base de données.

**Authentification requise** : Admin

**Audit** : L'action est enregistrée dans les logs d'audit

**Attention** : Cette action est irréversible.
        """,
        responses={
            204: {"description": f"{entity_title} supprimé avec succès"},
            401: {"description": "Non authentifié"},
            403: {"description": "Accès refusé - rôle admin requis"},
            404: {"description": f"{entity_title} non trouvé"},
            409: {"description": "Conflit - suppression impossible (dépendances)"},
            500: {"description": "Erreur serveur"},
        },
    )
    async def delete_entity(
        request: Request,
        admin_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        raw_id = request.path_params.get(id_field)
        try:
            entity_id = id_type(raw_id) if id_type != str else raw_id
            entity = await AdminRepository.get_by_id(db, model_class, entity_id)
            if not entity:
                raise HTTPException(status_code=404, detail=f"{entity_title} not found")

            entity_name_value = getattr(entity, 'name', None)

            if service_delete:
                await service_delete(db, entity_id)
            else:
                await db.delete(entity)
                await db.commit()

            await AuditService.log_action(
                db=db,
                action_name=f'{entity_name}_deleted',
                user_id=admin_user.id,
                resource_type_name=entity_name,
                resource_id=None,
                details={'id': entity_id, 'name': entity_name_value},
                request=request
            )

            REQUEST_COUNT.labels(endpoint=endpoint_name, method="DELETE", status="204").inc()
            return Response(status_code=204)
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            REQUEST_COUNT.labels(endpoint=endpoint_name, method="DELETE", status="500").inc()
            logger.error(f"Error deleting {entity_name}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    return router
