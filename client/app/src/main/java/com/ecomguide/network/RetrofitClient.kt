package com.ecomguide.network

import com.ecomguide.model.ApiProduct
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object RetrofitClient {
    /** Base URL for both REST API and image assets.
     *  10.0.2.2 = Android emulator → host machine localhost.
     *  Change to your machine's LAN IP when testing on a real device. */
    const val BASE_URL = "http://10.0.2.2:8000/"

    /** 统一图片地址解析：绝对地址直传，相对路径按后端规则补全。 */
    fun resolveImageUrl(rawUrl: String?): String? {
        val value = rawUrl?.trim().orEmpty()
        if (value.isBlank()) return null
        if (value.startsWith("http://") || value.startsWith("https://")) return value

        val base = BASE_URL.trimEnd('/')
        val normalized = value.removePrefix("/")

        val datasetRelative = when {
            normalized.startsWith("ecommerce_agent_dataset_/") -> normalized.removePrefix("ecommerce_agent_dataset_/")
            normalized.startsWith("ecommerce_agent_dataset/") -> normalized.removePrefix("ecommerce_agent_dataset/")
            normalized.startsWith("data/ecommerce_agent_dataset_/") -> normalized.removePrefix("data/ecommerce_agent_dataset_/")
            normalized.startsWith("data/ecommerce_agent_dataset/") -> normalized.removePrefix("data/ecommerce_agent_dataset/")
            else -> null
        }

        return when {
            normalized.startsWith("api/") || normalized.startsWith("static/") -> "$base/$normalized"
            datasetRelative != null -> "$base/static/$datasetRelative"
            normalized.startsWith("images/") -> "$base/static/$normalized"
            else -> "$base/${value.trimStart('/')}"
        }
    }

    /** 统一商品图片接口地址，作为所有页面兜底图源。 */
    fun productImageUrl(productId: String?): String? {
        val id = productId?.trim().orEmpty()
        if (id.isBlank()) return null
        return "${BASE_URL.trimEnd('/')}/api/products/image/$id"
    }

    /**
     * 商品图加载方案：
     * - displayUrl: 首选展示地址（字段图 -> 接口图 -> fallback 图）
     * - errorUrl: 加载失败后的兜底地址（接口图 -> fallback 图）
     */
    data class ProductImageSource(
        val displayUrl: String?,
        val errorUrl: String?
    )

    fun resolveProductImageSource(product: ApiProduct): ProductImageSource {
        val primaryUrl = resolveImageUrl(product.resolvedImageUrl)
        val endpointUrl = productImageUrl(product.resolvedId)
        val fallbackUrl = resolveImageUrl(product.img)

        return when {
            primaryUrl != null -> ProductImageSource(
                displayUrl = primaryUrl,
                errorUrl = endpointUrl ?: fallbackUrl
            )

            endpointUrl != null -> ProductImageSource(
                displayUrl = endpointUrl,
                errorUrl = fallbackUrl
            )

            else -> ProductImageSource(
                displayUrl = fallbackUrl,
                errorUrl = null
            )
        }
    }

    val instance: Retrofit by lazy {
        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }

    val api: com.ecomguide.network.ApiService by lazy {
        instance.create(com.ecomguide.network.ApiService::class.java)
    }
}
