package orders5

import "github.com/gin-gonic/gin"

type Store5 struct{}
func (s *Store5) Save() {}
type Service5 struct{ store *Store5 }
func (s *Service5) Create() { s.store.Save() }
type Handler5 struct{ service *Service5 }
func (h *Handler5) Handle() { h.service.Create() }
func Routes5(r *gin.Engine, h *Handler5) { r.GET("/orders/5", h.Handle) }
