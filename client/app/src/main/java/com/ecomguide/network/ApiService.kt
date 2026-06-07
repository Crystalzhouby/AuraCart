package com.ecomguide.network

import com.ecomguide.model.ApiProduct
import com.ecomguide.model.ChatRequest
import com.ecomguide.model.ChatResponse
import com.ecomguide.model.ProductSkusResponse
import com.ecomguide.model.ReviewResponse
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface ApiService {

    @POST("/api/chat")
    suspend fun sendMessage(@Body request: ChatRequest): ChatResponse

    /** Full product detail including rag_knowledge (FAQ + reviews) */
    @GET("/api/products/{id}")
    suspend fun getProduct(@Path("id") productId: String): ApiProduct

    /** Product list with optional filters */
    @GET("/api/products")
    suspend fun getProducts(
        @Query("category") category: String? = null,
        @Query("q") query: String? = null,
        @Query("limit") limit: Int = 20
    ): ProductListResponse

    /** GET /api/review/{product_id} */
    @GET("/api/review/{id}")
    suspend fun getProductReview(@Path("id") productId: String): ReviewResponse

    /** GET /api/all_skus/{product_id} */
    @GET("/api/all_skus/{id}")
    suspend fun getAllSkus(@Path("id") productId: String): ProductSkusResponse
}

data class ProductListResponse(
    val total: Int,
    val products: List<ApiProduct>
)
