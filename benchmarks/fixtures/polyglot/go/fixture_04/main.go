package orders4

import "github.com/gin-gonic/gin"

type Store4 struct{}
func (s *Store4) Save() {}
type Service4 struct{ store *Store4 }
func (s *Service4) Create() { s.store.Save() }
type Handler4 struct{ service *Service4 }
func (h *Handler4) Handle() { h.service.Create() }
func Routes4(r *gin.Engine, h *Handler4) { r.GET("/orders/4", h.Handle) }
