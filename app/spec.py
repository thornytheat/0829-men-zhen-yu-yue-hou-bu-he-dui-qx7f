COLUMNS = ('slot', 'attendee', 'minute', 'priority', 'expires')
KINDS = ('initial', 'wait', 'cancel', 'audit')
PROJECT = {'name': '门诊预约候补核对', 'actor': '门诊排班管理员', 'stages': [('intake', '样例采信'), ('prepare', '预约事件验收'), ('calculate', '候补复算'), ('policy', '号源平衡'), ('balance', '运行对账')], 'chart': '号源占用', 'mark': '门'}
