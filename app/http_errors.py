from flask import jsonify

LABELS = {
    'FILE_TOO_LARGE':'文件超过 256 KiB', 'FILE_EMPTY':'文件没有内容', 'FILE_BLANK':'文件只有空白',
    'HEADER_ONLY':'文件只有标题行', 'HEADER_MISMATCH':'列名与字段字典不一致', 'ENCODING_INVALID':'请使用 UTF-8 CSV',
    'CSV_MALFORMED':'CSV 引号或行格式异常', 'ROW_LIMIT':'文件超过 2000 行', 'FILE_REQUIRED':'请选择 CSV 文件',
    'RUN_NOT_FOUND':'批次不存在', 'REVIEW_FIELDS':'请填写 3 至 200 字复核意见', 'STALE_REVIEW':'批次已更新，请刷新',
    'RUN_FINALIZED':'批次已签发', 'UNRESOLVED_ISSUES':'存在待处理差异', 'SAMPLE_UNKNOWN':'样例不存在', 'STAGE_UNKNOWN':'处理阶段不存在',
    'BOARD_NOT_FOUND':'交接台不存在', 'GROUP_NOT_FOUND':'业务分组不存在', 'CERTIFICATE_NOT_FOUND':'签发件不存在',
    'GROUP_FINALIZED':'分组已签发', 'GROUP_HELD':'分组已暂缓', 'CROSS_GROUP_CONFLICT':'跨组记录冲突，相关分组均须暂缓',
    'UNRECOGNIZABLE_GROUP':'坏行连分组都认不出，所有未签发组暂缓',
}


def response(error):
    code = error.code
    status = 404 if code in {'RUN_NOT_FOUND','SAMPLE_UNKNOWN','STAGE_UNKNOWN','BOARD_NOT_FOUND','GROUP_NOT_FOUND','CERTIFICATE_NOT_FOUND'} else 409 if code in {'STALE_REVIEW','RUN_FINALIZED','UNRESOLVED_ISSUES','GROUP_FINALIZED','GROUP_HELD','CROSS_GROUP_CONFLICT','UNRECOGNIZABLE_GROUP'} else 413 if code=='FILE_TOO_LARGE' else 422
    body = {'code':code,'message':LABELS.get(code,code)}
    aliases = getattr(error, 'aliases', None)
    if aliases:
        body['aliases'] = list(aliases)
    return jsonify(body),status
