# 项目文件命名规范化

## server/app//agent/nodes/下的agent文件

extraction.py-> intent_extract_agent.py
option_gen.py->option_generate_agent.py
retriever.py->product_retrieve_agent.py
router.py->intent_route_agent.py
scenario_gen.py->scene_generate_agent.py

## /server/app/agent/prompts下的提示词文件

category_intro_prompt.py->category_introduct_prompt.py
extraction_prompt->intent_extract_prompt.py
option_gen_prompt.py->option_generate_prompt.py
product_reason.py->product_recommendation_prompt.py
scenario_gen_prompt.py->scene_generate_prompt.py
unified_router_prompt->intent_router_prompt.py

## server\app\api
products.py->get_product_info.py
conversation.py->get_conversation.py

此外注意更改上述文件名的同时，也相应地规范化变量名和函数名。