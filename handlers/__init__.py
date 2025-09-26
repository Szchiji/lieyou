from . import menu, checkin, member, autoreply, schedule

def register(application):
    menu.register(application)
    checkin.register(application)
    member.register(application)
    autoreply.register(application)
    schedule.register(application)
