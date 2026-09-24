from . import services

def roles(request):
    return {"is_support": services.is_support(request.user),
            "is_manager": services.is_manager(request.user)}
