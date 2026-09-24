from django.contrib import admin
from .models import Category, Ticket, TicketActivity

admin.site.register(Category)
admin.site.register(TicketActivity)

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "category", "status", "priority", "assigned_to", "due_at")
    list_filter = ("status", "priority", "category")
